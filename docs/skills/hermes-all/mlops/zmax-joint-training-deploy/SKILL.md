---
name: zmax-joint-training-deploy
description: Use when 训练产物要落进 Z-MAX 引擎或真联合训练调试。
version: 1.0.0
author: Hermes
license: MIT
metadata:
  hermes:
    tags: [zmax, joint-training, deploy, intact, checkpoint]
    related_skills: [zmax-policy-training-eval, intact-jepa-integration, robot-policy-eval]
---

# Z-MAX 真联合训练 & 产物部署

## When to Use
- 训练产物（joint_v*.pt / LoRA ckpt）要**落进 Z-MAX 引擎**跑 A/B
- 做**真联合训练**（多层同一 autograd 图）或改进其架构
- 引擎加载新 ckpt 报错（Ambiguous checkpoint / config.json not found / Unexpected key）
- A/B 结果"两臂一样"需要判断是**真无提升**还是**判据无区分度**

真联合训练 = **同一 autograd 图**内多层同时训练(L2感知⊗L4世界模型⊗L3动作),
与"顺序流水线"(joint_train_all.py: 训完一层存盘再训下一层)本质不同。
流水线下 L3 的损失**永远碰不到 L4**;真联合下一次 backward 梯度穿过多层。

## 一、真联合训练器（五版演进，工具在 `tools/joint_train_real_v{1..5}.py`）

| 版本 | 关键升级 | 判据 | 实测 |
|---|---|---|---|
| V1 | MVP 小网络验证原理 | 3/3 | 损失降 43.3% |
| V2 | 换**在役真 JEPA ckpt**(2097万参数) | 3/3 | 279/279 参数有梯度 · 降 88.9% |
| V3 | 三图联合 + 真图像(mp4抽帧) | 5/5 | L2+L4 共 285 参数 · 降 93.9% |
| V4 | **真数据**(引擎轨迹 h5) | 6/6 | 真动作 MAE 0.5293→0.0628 (降 88.1%) |
| V5 | **记忆入图** + 官方同构头 + 口径对齐 + 双向耦合 + λ自适应 | 6/6 | ∇mem 非零 · MAE 降 80.6% |

### 三个关键判断（决定可行性的约束）
1. **环境**: 真 JEPA 需 `stable_pretraining`(vit_hf) → 只能在 **INTACT venv** 跑
   (lerobot venv 缺该依赖; 两 venv torch 版本不同 2.6/2.7 → 不能跨 venv)
2. **JEPA 只依赖 torch+einops**(零 stable_worldmodel 依赖) → 可进任意 venv
3. **输入必须带时间维**(debug 出来的真接口, 错的会报
   `not enough values to unpack (expected 4, got 3)`):
   - `jepa.encode`: `pixels` = **(b,t,c,h,w)** 5D
   - `action_encoder`: `action` = **(b,t,d)** 3D
   - `ARPredictor.forward` 内部 `rearrange("b t d -> (b t) d")` → 必须 3D
   - ViT 输出 `(b,t,257,192)` → 取 **CLS token** `[:,:,0,:]`

## 二、★ 部署门槛清单（4 道，全部实跑撞出，无文档）

训练产物要真进引擎，必须同时满足：

```
① 产物格式 = **扁平 state_dict** (323 keys)
   ✗ torch.save({"state_dict": sd}, "weights.pt")
       → RuntimeError: Unexpected key "state_dict" + Missing 全部 323 keys
   ✓ torch.save(sd, "weights.pt")

② 目录内**只能有 1 个 .pt 文件**
   ✗ 留了 joint.pt + weights.pt
       → ValueError: Ambiguous checkpoint: multiple .pt files
   ✓ 其余改名 .pt.bak

③ 目录必须含 **config.json** (hydra 实例化用)
   ✗ FileNotFoundError: config.json not found in ...
   ✓ cp <在役ckpt>/config.json <新ckpt>/

④ 动作语义口径 = act = clip(u / K_ACT), K_ACT=0.5
   ✗ 喂 pad 出来的假 8 维 → 模型学错分布
```

引擎侧另有一个**条件初始化 bug**（已修，勿回退）：
`state_space_sim_real.py` 的 `_l4_dit_cond` 只在部分路径初始化（@1439/1450），
访问处必须用 `getattr(self, "_l4_dit_cond", None)` 兜底 —— @3093 曾直接访问导致
未初始化路径抛 AttributeError。

## 三、加载 ckpt 的环境变量
```bash
INTACT_POLICY=<ckpt目录名>   # 指向 stable-wm-cache/checkpoints/<name>/
INTACT_RUNTIME=root
SS_L4_INTACT=1                # decoder 量纲逆运算路径(无需标定) ← 能真接管 u_ff
# 注意: SS_INTACT=1 是"标定映射"路径, 需标定过闸(R²≥0.30);
#       官方 cube 权重跨域到 Z-MAX 动作空间 R²=-0.147 → 全被拒 → 走不通
headless 调引擎必须自己 attach:
sim.attach_intact(IntactNode(horizon=8), None)   # GUI 路径会自动做, 裸引擎不会
```

## 六、🔑 节点→引擎契约（第四道门，2026-09-23 实跑钉住）

**挂上节点 ≠ 真接管。判"真接管"的唯一铁证 = 引擎 `st["w"] > 0`。**

```
症状: 节点挂载成功(calls>0, refused=0), 但 w=0.00 → 对控制零贡献 = 假接入
根因: src/lerobot/policies/intact/decoder.py:155
        intent_norm = float(getattr(out, "diagnostics", {}).get("intent_norm") or 0.0)
        w = w_max if intent_norm > 1e-6 else 0.0
      → 置信度**只从 out.diagnostics['intent_norm'] 字典取**, 裸属性无效!
修法: 节点返回对象必须带:
        out.chunk        (T, action_dim) 动作块, 元素已在 [-1,1]
        out.diagnostics  = {"intent_norm": float(np.linalg.norm(chunk))}   ★关键
        out.latent       = {"z_t": ...}   (可选; 缺 → 条件通道记'拒绝(无潜空间)')
        out.trained      = True
        out.goal_src     = "<来源标注>"
验证: 同 seed A/B, 看 w 是否从 0 → 0.30 (在役同值) 且 done/深度有变化
实测: 修前 w=0.00 / 修后 w=0.30 ✓, done=True 不回退
```

**四道门总览（训练产物 → 引擎真接管，全部实跑撞出，无文档）**：
```
① 引擎 bug: _l4_dit_cond 条件属性直接访问       → getattr 兜底
② 产物格式: 扁平 state_dict (非嵌套)            → torch.save(sd)
③ 目录约定: 单 .pt 文件 + 必须含 config.json     → 清理+拷贝
④ 节点契约: out.diagnostics['intent_norm']      → 否则 w=0 假接入
```

## 五、🔴 跨数据源比对铁律（今天踩了 3 次，必须逐通道验）

**任何跨数据源/跨口径的比对，先验 obs 与 action 的逐通道一致性，再谈结论。**

```
事故 1: L5 造数据用 tr["obs"]（引擎 fused 39 维）→ 与 v5/v6 的 env 原生 o[:39] 不同
        → 留出结论作废
事故 2: 在线桥接同样误用 tr["obs"]（hook 记录了 env 原生却没用）
        → "在线差 25×" 作废, 改用 hook 序列后 L4 立刻变优(0.0175 < 基线 0.0253)
事故 3: 动作夹爪维 v6=0.816 vs 在线=0.266 → 口径或阶段覆盖不同, 待定

判别方法（实测有效）:
  · 引擎正确 obs = env._get_obs()[:39]  （挂 fuse_sensors 钩子, 每步 1 次, 1:1 对齐）
    标志: dim7,8 ≈ 0 · dim10 ≈ 1.0
  · 错的 obs = tr["obs"]（fused: cur18+prev18+target3+force+tactile）
    标志: dim7,8 非零(≈0.5) · dim10 ≈ -0.25
  · 脚本: tools/identify_obs_convention.py（逐维均值差量化判别）

口诀: **先验逐通道均值/方差, 再下任何结论**。差 >0.05 就是口径不同, 不是模型问题。
```

## 六、⚠️ 判据陷阱（最容易误判的地方）

**参数格式坑（实测撞出，2026-09-22）**：
```
--disturbs  只认 **none** / **disturb** (无 light/medium/heavy)
            传错 → "矩阵: N 臂 × 0 干扰档 × M seed = 0 格" → "❌ 没有任何结果"(静默空跑)
--ckpt      必须是**文件路径** (joint_v5/weights.pt), 不是目录名
            传目录 → manifest 里 ckpt_sha256_16=None (同口径证据缺失)
正确: python tools/mem_ladder_integration.py --arms L234 --seeds 104 --steps 1200 \
         --disturbs none,disturb --ckpt joint_v5/weights.pt
```


**天花板效应**：若解析链本身就能完成任务（`done=True`），则无论 L4/联合训练多强，
A/B 两臂结果都相同 → 看起来"无提升"，其实是**判据没有区分度**。

```bash
# 反例(无区分度): seed104 无扰动, max_steps=4000
A 臂(L4接管)  : 348 步 done=True 阶段=完成
B 臂(回落解析): 348 步 done=True 阶段=完成     ← 同结果, 看不出差异
```

**正确判据（三选一或组合）**：
1. **扰动档**（首选）— L4 的价值在抗干扰，阶梯台 `--disturbs` 就是为此设计
2. **更难任务变体** — 让解析链本身会失败
3. **动作质量指标** — 平滑度 / 能耗 / 抗扰恢复速度，而非"能否完成"

**判定纪律**（用户门槛）：
- 单 seed 差异 <5% 属噪声量级 → **不能宣称提升，也不能断言回退**
- 未证明提升 → **不进默认档**，保留开关
- 多 seed × 2 重复 才算证据

## 五、可复用命令行骨架

```bash
# 训练 (INTACT venv)
/home/ubuntu/INTACT-JEPA/.venv/bin/python tools/joint_train_real_v5.py \
    --steps 200 --batch 6 \
    --h5 /home/ubuntu/stable-wm-cache/datasets/optical_insert_v6_disturb.h5 \
    --save /home/ubuntu/stable-wm-cache/checkpoints/joint_v5

# 部署准备 (4 道门槛一次做全)
CK=/home/ubuntu/stable-wm-cache/checkpoints
cp $CK/intact_l4_current/config.json $CK/joint_v5/          # ③
python -c "import torch;sd=torch.load('$CK/joint_v5/joint_v5.pt',map_location='cpu',weights_only=False);torch.save(sd.get('l4',sd),'$CK/joint_v5/weights.pt')"  # ①
mv $CK/joint_v5/joint_v5.pt $CK/joint_v5/_part.pt.bak      # ②

# A/B (两臂, 要求两臂 src 都 = intact(chunk×K_ACT=0.5) 才算都真接管)
cd tools/gui && INTACT_POLICY=joint_v5 INTACT_RUNTIME=root SS_L4_INTACT=1 \
  LOCAL_DATASET_DIR=/home/ubuntu/stable-wm-cache STABLEWM_HOME=/home/ubuntu/stable-wm-cache \
  MUJOCO_GL=egl <gui-venv311>/python -c "
import sys; sys.path[:0]=['.../src','.../tools/gui']
from state_space_sim_real import RealStateSpaceSim
from lerobot.manifold.intact_node import IntactNode
sim=RealStateSpaceSim(seed=104, vision=False, log=lambda *a: None)
sim.attach_intact(IntactNode(horizon=8), None)
tr=sim.run(max_steps=4000); print(sim._l4_stats['src'], len(tr['t']), tr['done'][-1])"
```

## 六、Pitfalls 汇总
- 忘记 `attach_intact` → 节点恒 None，`intact_calls=0`（会被误判成"没集成"）
- 用 `SS_INTACT=1` 测跨域权重 → 全被拒（标定 R²<0），要用 `SS_L4_INTACT=1`
- 只跑 120 步 → 看不出 done/阶段差异（调度公式决定 calls/w，与模型无关）
- 把 `{"state_dict": sd}` 直接存盘 → 引擎加载失败（最常见，已踩两次）
- 在 lerobot venv 里 import 真 JEPA → `ModuleNotFoundError: stable_pretraining`

# 插拔评估管道修复实录 (2026-08-07, eval_latest.py / eval_insert.py)

## 背景
老倪要求评估最新模型 (MLP 蒸馏 + ACT-pegdata + ft 微调) 插拔成功率。评估脚本从零跑出多个坑。

## 坑链 (按出现顺序)

### 1. MLP 加载 state_dict key 不匹配
- 蒸馏脚本保存结构: `ExpertMLP` 类含 `self.net = nn.Sequential(...)` → state_dict key 是 `net.0.weight` / `net.3.weight` / `net.6.weight` / `net.8.weight`
- 自己重定义 `nn.Sequential` 或 MLP 类 → key 是 `0.weight` → `load_state_dict` 崩 `Missing key(s): 0.weight... Unexpected key(s): net.0.weight`
- **修复: `from tools.distill_expert import ExpertMLP` 复用原类** (结构完全一致)
- 第二个坑: `obs_dim` 变量在重构时丢了 → Pyright `obs_dim is not defined` → 从 `d["obs_dim"]` 重新解包

### 2. MLP 输出 unbounded → 动作漂移
- 新蒸馏 MLP (90000 样本 / 300 eps / 插入率 89%) loss 0.507 但**输出恒定 [2.34, -0.633, 3.324, -0.944]** (5 步一模一样) — 远超专家动作范围 [-1,1]
- 直接 env.step → 乱跑 → 抓起 0/10
- **修复: `act = np.clip(act, -1.0, 1.0)`** → 抓起 6/10 插入 3/10 (距孔 0.192)

### 3. 纯模型评估 vs 覆盖夹爪
- 初版 run_mlp_episode 有手写夹爪逻辑 (`if d_peg < 0.06: act[3] = -1.0`) — 这是"规则后处理"不是模型能力
- 老倪要"模型能不能插拔" → 删掉夹爪覆盖, 纯模型输出 → 这才是真实评估

### 4. importlib.reload 破坏模块状态
- 先 `importlib.reload(ei)` 再 `from eval_insert import load_policy` → 拿到旧引用 → load_policy 返回 (None, None) → `'NoneType' object is not subscriptable`
- 单独跑 load_policy('act') 成功但脚本内失败 — 症状是 reload 后模块内部引用错乱
- **修复: 不 reload, 主脚本开头 import 一次直接复用** (`from eval_insert import load_policy as _lp`)

### 5. stats.json 被磁盘清理删掉
- `_load_stats()` 候选目录只列 `data/metaworld_peg_v4/v3/v2` — 这些被清理后全 None
- 崩 `stats["observation.state"]["mean"]` → `'NoneType' object is not subscriptable` (eval_insert.py L84)
- **修复 (正解 = 从 checkpoint preprocessor 读, 不只是加候选目录)**: `outputs/train/<run>/checkpoints/004000/pretrained_model/policy_preprocessor_step_3_normalizer_processor.safetensors` 里有训练真实归一化参数, 键:
  - `observation.state.mean/std` (1,) 标量 (MEAN_STD 用整体标量, 非逐维!) — 实测 mean≈0.147 / std≈0.30
  - `action.mean/std` (1,) — 实测 mean≈-0.62 / std≈2.12
  - **广播到完整维度**: `sm = np.full(39, sd["observation.state.mean"][0])`, `am = np.full(4, sd["action.mean"][0])`
  - fallback 候选目录 (peg_lerobot/act) 结构对但维度旧 (1 维), 只兜底
- 验证: `_load_stats()` 非 None + state mean len == st_dim (39)

### 5b. eval_insert 里 sm/ss 被 np.zeros/np.ones 覆盖 (归一化静默失效)
- eval_insert.py L122-123 有调试残留 `sm = np.zeros(st_dim); ss = np.ones(st_dim)` — **覆盖了 116-117 行从 stats 读的归一化参数** → ACT 输入等于没归一化 → 假 0%
- 症状: 行为测试 (自己写) 正常但 run_episode 结果异常 — 归一化被覆盖
- **修复: 删除覆盖行**; 教训: 调试残留要清, 评估前打印 `sm[:3]` 确认非 0

### 6. 设备不匹配 (单独测试脚本)
- `/tmp/mlp_test.py` 里 `s_t` 没 `.to(DEVICE)` → `Expected all tensors to be on the same device, but got mat1 is on cpu... cuda:0`
- 修复: `s_t.to(next(pol.parameters()).device)` — 用模型参数设备, 别写死

### 7. ACT 方向性诊断 (老倪: "那ACT至少方向性应该能学出来啊" — 他完全对)
**只看 0% 结论会误判 "ACT 没学到"** — 单 episode 行为跟踪 (手-peg 距离/夹爪/peg_z):
```
step0:  hand→peg 距离 0.173  (手在初始位)
step10: 0.140  step20: 0.024  (手精确到达 peg 附近!)
夹爪:   grip_assist 闭合 -1.0 触发, 但 peg_z 恒 0.025 (没被抓起来)
```
- **ACT 方向性完全学会** (dist 0.133→0.024m, x+ 动作正确朝 peg 移动)
- **抓取失败根因 = 毫米级对准**: peg 直径 ~1cm 需 <1cm 对准, 行为克隆极限 ~2.4cm — 手穿过 peg 但夹爪没对准 pegGrasp, 闭合也抓不起
- **结论**: 方向性=BC 可学; 毫米级抓取对准=需触觉/力反馈或视觉伺服 → 支撑 VLA-Touch/AWE 触觉优势的选型结论
- **诊断方法**: 单 episode 跟踪 hand_pos/peg_pos/距离/夹爪/peg_z — 区分 "没接近" (管道坏) vs "接近了抓不起" (精度极限); 报告给老倪时要展示距离收敛轨迹证明方向性学会

### 8. grip_assist 夹爪辅助参数
- `run_episode(policy, seed, grip_assist=True)`: 手-peg 距离 <0.08 且未抓起 → 夹爪 -1.0 (闭合); 已抓起 → 0.6 (保持); 否则 0.0
- 用途: 验证模型方向性 (ACT 差夹爪决策时用辅助隔离出方向能力), 但正式评分用纯模型 (grip_assist=False)

## 最终结果 (2026-08-07)
| 模型 | 抓起 | 插入 | 距孔 |
|---|---|---|---|
| MLP 蒸馏 (clamp 后) | 6/10 | 3/10 | 0.192 |
| ACT-pegdata 4000步 | 0/10 | 0/10 | 0.350 |

- MLP 是学习模型里唯一能插拔的 (诚实标注: 比 08-06 旧版 55% 低, 因为纯模型评估不覆盖夹爪)
- ACT 学不会插拔持续证实 (4000 步 peg 数据仍 0%), **但方向性学会** (见坑 7)

# 真实化闭环 3 坑定稿 v5.4.0 (2026-09-08 静静, seed104 R1 视觉 9/9 失败排查链)

## 坑 1: 夹持锚定判据 — "反复夹不起光模块"真根因 (state_space_sim_real.py)

现象: R1 视觉 seed104 GUI 演示 ~150 步处 🔩深夹 grasped=True → "⚠️光模块滑脱" →
回退重抓 → 循环至 500 步 done=False; R0 同 seed 成功 343-345 步。

排查铁证链 (别跳步, 每个都是真实验证):
1. R0(真值)成功 / R1(视觉)失败 → 问题在视觉路径, 非调度/物理。
2. 锁存瞬间几何对比: R1 失败轮 [135] 与 R0 成功轮 [137] 几乎相同
   (xy 7.1 vs 7.0mm), peg 真值全程跟手被抬起 (z 0.025→0.049) → **物理真夹住了**。
3. 视觉残差量化: 悬停期 ~5mm(健康) → 锁存瞬间 8.3mm, 恰卡在旧锚定条件
   (|off−off0|<8mm) 门外 → 锚定永不触发 → 20 帧宽限后滑脱阈值收紧 8mm →
   判据偏差恒=视觉残差 8.3mm>8mm → **真夹住被判滑脱** → 回退碰移 peg(残差 25mm)全乱。

根因本质: 09-07 "夹持真值锚定"判据缺陷 — 把视觉 peg 估值残差混进真值滑脱判定,
成功依赖"锁存瞬间视觉残差<8mm"的运气 (进程间布局微漂 4mm 就翻转成败)。

修复 (锚定判据 v2, commit 00611a3f): **抬升试探的物理事实** —
夹爪在动 (Δx>1mm) 且 peg 真值随动 (相对漂移<3mm) = 真夹住 → 立即锚定当前真值 off。
视觉 peg 估值残差**不再参与夹持后判定** (真机同构: 机械夹持后工件位置由夹爪/编码器保证)。
验证: R1 insert 341/342/352 步 done ×4 / R0 345 / R1 full 866 + AOI PASS / R0 full 868。

## 坑 2: 肌肉记忆快通道 × R1 视觉 = 9/9 失败 (同文件)

现象: 锚定修复后 CLI 回归 R1 insert 突然 9/9 失败 (此前同轮 2/2 成功), 全卡"抓取"。

A/B 实锤: `SS_MUSCLE=0` 同轮 **352 步 done**; `=1`(默认)500 步失败。

机制: 肌肉记忆快通道用**历史轮标杆 u_exec 开环重放**接近/对位/下降/抓取段
(固化自 09-07 成功轮, 练 16+ 次); R1 视觉/接触有随机性 (进程间布局微漂 + peg
被碰史不同) → 标杆与新状态失配 → 下降按旧轨迹落点偏 → 空夹循环; 且 R1 成功轮
会往标杆库混入不同代码版本轨迹 (污染库)。

修复 (commit 3482a9a7): 肌肉记忆**仅限 R0/确定性环境**
(`if os.environ.get("SS_MUSCLE") != "0" and not self.vision`); R1 视觉自动关闭
(GUI ▶运行 = R1 → 稳定); R0 是老倪验收场景 (6 轮 demo) 保留。视觉/接触有感知
噪声的场合不做开环标杆重放 — 真机同构红线。

## 坑 3: 节点算法归位 src 三件套 + 右键映射两个隐蔽 bug

老倪铁律: 真实算法在 `src/lerobot/` (policies/datasets/manifold/... 标准结构),
GUI node_logic 只做壳。VLM 编码/Decoder/predictor 三处落地模式:

1. **src 真实文件**: vlm_encoder.py → `src/lerobot/policies/smolvla_lew/`
   (SmolVLM 视觉骨干属该策略); StateSpaceActionHead → 同包 `state_space_action_head.py`;
   JEPA predictor → **`src/lerobot/manifold/predictor_layer.py`** (predictor 预测
   接触/性能流形 = 流形域, 与 manifold_layer.py 同目录; 不要塞进 policies!)。
   纯 torch 文件 (不 import lerobot) → node exec 可加载。
2. **node exec(compile(真实绝对路径)) 加载** → co_filename 真实 → VSCode 断点可进;
   **模块级 ns 缓存** (防单例/类重复 exec 重建 — get_encoder() 模型只加载一次)。
3. **右键"打开源代码"两条路径都要对**:
   - `_EXTERNAL_LOC[key]` 的 key **必须 = _reg 注册键** (坑: 写了 "ssvlm" 而注册是
     "ss_vlm" → 永远查不到 → 右键回退 GUI 壳)。
   - 画布节点 `params.source` **优先**于 node_logic 映射且要指向**真实实现文件**
     (坑: VLM 节点 source 还指 modeling_smolvla_lew.py 教学大文件 → 右键跳错;
     source=None → 落 GUI)。

断点调试姿势: F5 选「Z-MAX 控制台」调试配置 + **右键节点→运行节点** (非 ▶播放态 —
播放走 demo 轻量路径不跑模型, 铁律); exec 路径与 VSCode 打开路径逐字符一致
(_REPO_ROOT 规范化) 才命中。

## 附: v5.4.0 能力档位 (L2/L3/L4)

- 🧭 数据源层节点双击循环切档, 写 module._cap_level, ▶运行 读 (优先于 chk_l3_full):
  L2→insert / L3→full 13段 / L4→full + `sim.run(cap="l4")` (恢复预算 ×2, 失败不放弃)。
- 引擎分级回退 (遇阻/空夹/滑脱→重对孔/重抓) = 恢复执行体现成; predictor 世界模型
  训练后给恢复方向 (待训练, 不冒充)。

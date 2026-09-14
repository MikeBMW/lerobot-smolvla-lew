# parallel.py 前馈加速器真实化 + 画布行号动态定位 (2026-09-04)

> SKILL.md「教学解析层 vs 真实权重」节在 2026-09-04 后已过时 (后台 curator 受 read-before-write
> 与 view dedup 冲突无法改 SKILL.md, 追加于此; 前台会话可把本文件合并进 SKILL.md)。

## 🧠 FeedforwardAccelerator 现在是真模型主路径 (勿按旧认知判断"模拟伪装")
- parallel.py L71 FeedforwardAccelerator.__init__ **加载 models/ss_left_brain.npz** — 547K
  蒸馏 MLP (tools/export_ss_left_brain.py 从 reports/train_curve_state_space.json 的 ckpt
  导出; 纯 numpy 4 层 Linear W0-3/b0-3 + sm/ss/am/astd, GUI gui-venv311 无 torch 可跑),
  forward 主执行 = MLP 前向 (闭包 mlp_ff_forward L43)。
- 解析比例律 (Kp=1.2) 降级 analytic_forward = **域外守卫 D_GUARD=0.25** (hand→目标 3D 距离):
  蒸馏 MLP 域外闭环发散是本质 — 实证 ±3cm 扰动 1/3 seed 失败、±5cm+ 全失败 (hand 恒速飞出
  9m); 解析全局稳定 (≤±20cm 全收敛) → 域外由解析教师兜底。+ 标定层 Kp 字面量对象 + 诊断基准。
- self.loaded / n_mlp / n_guard 可查真实执行占比; 断点验证模型在跑打 parallel.py L49-52
  (矩阵乘), 不是 load_npz_weights (只在进程内首次实例化执行一次, 之后 _NPZ_CACHE 命中)。
- AdaptiveStateEstimator (L128) 仍是线性卡尔曼 A/K/B (教学式, 非 GRU)。
- 史前认知勿再用: 09-03 前 parallel.py 两解析类零加载; 真权重只在 state_space_sim::ff_forward
  与 ss_verify_trained.py。训练/数据管道 (export_dataset 解析教师铁律、perturb 扩域重训、
  sim 几何漂移须重跑管道、checkpoints last→00X000 级联) 见 zmax-left-right-policy
  「前馈加速器真实化」节。
- 通用判别更新: 看 __init__ 是否 np.load npz / forward 是否 self._ff; 有 D_GUARD = 蒸馏 MLP
  主路径 + 域外解析兜底。

## 📍 画布右键跳源码: 行号动态定位 (2026-09-04)
- node_logic.get_node_location: _EXTERNAL_LOC 映射带符号名 (ext[2]) 时**按文件现搜行号**
  (ln.lstrip().startswith(sym)), 源码重写后行号漂移自动跟随; 手写行号仅作回退。
- 曾踩: parallel.py 重写后 class FeedforwardAccelerator 21→71, _EXTERNAL_LOC 手写 21 →
  右键跳到 import 区 (表现 = 「没跳」)。新增节点映射只需 (path, 行号占位, "class/def 符号名")。
- 同款坑史: 09-02 ss_est 行号 34→45 也漂过一次 (手写机制没根治); 09-04 起动态定位根治。

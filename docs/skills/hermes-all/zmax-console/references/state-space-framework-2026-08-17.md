# 状态空间模块化框架 (2026-08-17) — src/lerobot/policies/left_right/state_space/

老倪需求: "所有代码都不能放到 tools/ 下; 参考 lerobot 架构放 src/lerobot/policies/left_right/
modeling_left_right.py 这样的地方; 模块化设计, 符合 simulink 设计哲学 + lerobot 生态"

## 硬性规则

- **代码不进 tools/**: 新框架全部在 `src/lerobot/policies/left_right/state_space/`。
  tools/ 下旧脚本 (ff_pd_analysis.py / eval_state_space.py) 保留为 CLI 入口
  (simulink on_eval_state_space 仍子进程调用), 但画布 source 一律指向 src/。
- **画布节点 ↔ 代码一一对应**: flows/state_space_obs.json 的每个节点 id
  (sssensor/ssff/sssched...) ↔ state_space 包里一个 Block 类 ↔ params.source 指向该模块文件。
- 右键「打开源代码」: simulink_module.py `_on_context_menu` 里
  `if _nsrc.startswith("src/") or _nsrc.startswith("tools/")` 才显示菜单项
  (2026-08-17 扩展支持 tools/; open_node_source 复制到 C:\zmax_src_view + explorer 打开)。

## 框架结构

```
src/lerobot/policies/left_right/state_space/
├── __init__.py      # 导出 Block 类 + StateSpaceModel + build_state_space_model
├── blocks.py        # Block 基类: in_ports/out_ports + step(u:dict)->dict + _in/_out/_emit + reset
├── perception.py    # S1: SensorFusionBlock(📡) → StateVectorBlock(🧩43D obs)
├── parallel.py      # S2: FeedforwardAcceleratorBlock(⚡快) ‖ StateEstimatorBlock(🔮慢, 卡尔曼)
├── dynamics.py      # 📈PriorPredictorBlock → 🧪InnovationDetectorBlock (残差&接触, 校正)
├── cognition.py     # S3: CognitiveSchedulerBlock(🧭否决权, u=w_ff·u_ff+(1-w_ff)·u_fb)
├── safety.py        # 🛡SafetyBoundaryBlock (饱和限幅)
├── execution.py     # 🤖ExecutorBlock → 🌍WorldBlock (z_k 反馈闭环)
├── model.py         # StateSpaceModel: 顶层装配 + step() 单步 + run(n) 闭环 (z_k 回灌创新检测)
└── analysis.py      # 📊 前馈PD对比 (run_compare/plot_compare) + L2增益/BIBO/谱半径
```

## Block 基类契约 (踩坑记录)

```python
class Block:
    in_ports: List[str] = ["in1"]
    out_ports: List[str] = ["out1"]
    def step(self, u: Dict[str, Any]) -> Dict[str, Any]: raise NotImplementedError
    # _in(port) 读输入(带 _last 记忆) · _out 记录 · _emit(**outs) 记录并返回 dict
```

- **step 必须返回 dict {port: value}** — 最初 `_out` 返回裸值导致
  `fused["obs_43d"]` 变成 numpy 数组索引报错 (IndexError: only integers...)。
  修复: 加 `_emit(**outs)` 统一收尾。
- **调用方解包**: `innov = b["ssinnov"].step(...); info = innov["out1"]` —
  不要写成 `innov1, innov2 = step(...)` (dict 解包拿到的是 key 字符串 "out1"/"out2",
  AttributeError: 'str' object has no attribute 'get')。
- 无模型时 Block 退化行为: 前馈=零, 估计器=一阶低通, 世界=带噪恒等 — 画布/分析可独立跑。

## 验证 (gui-venv 无 lerobot 依赖)

gui-venv (PyQt5 用) 没有 lerobot/huggingface_hub → `import lerobot...` 触发
policies/__init__.py 全家桶失败。验证方法: 伪造最小包链 (types.ModuleType + sys.modules
注册 lerobot 三级路径) 再 spec_from_file_location 加载 state_space 包; 或直接
python -c 从 src/ 下用 importlib 按依赖序加载模块文件。模型闭环验证:
单步 step() → run(5) contact 序列 → analysis.analyze_model() → run_compare() 应全部跑通。

## 主题铁律 (同会话老倪纠正)

默认启动 = 暗夜, **不得预设浅色主题** (老倪: "你不能自己改成浅色调")。
主题持久化 ~/.zmax_ui.json 只在用户手动切时写; agent 删文件 = 回默认。

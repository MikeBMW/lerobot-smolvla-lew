# Simulink Flow JSON 生成器模式 (2026-08-10 三连复用)

把 GUI/代码对象/实验结果 → simulink 画布可加载 flow JSON 的标准三步：
**gen 脚本 → flows/*.json → 模块库 flow 按钮 → offscreen 验证**

## 已落地实例 (tools/gui/gen_*.py + flows/*.json)
- `gen_hardware_toolbox_flow.py` → `flows/hardware_toolbox.json` (硬件工具箱全部可控对象: Z700关节14+相机7+Orin总线12+IO5, 42节点32连线)
- `gen_dual_brain_flow.py` → `flows/dual_brain_peg.json` (left_right 工程: 左脑LeftBrainMLP+右脑RightBrainWM+状态机, 22节点21连线)
- `gen_transfer_adaptive_flow.py` → `flows/transfer_adaptive.json` (实验总结: 降波动三实验+根因, 18节点17连线)

## gen 脚本骨架 (复制改)
```python
def add_node(p, i, ntype, name, x, y, params, w=150):
    # icon/color 字典按 NODE_TYPES 映射; id = f"db{p}{i}" 任意字符串即可
    # 节点必须含 inputs/outputs (in1/out1, dtype any) — load_flow_file 依赖
def add_link(f, t, label=None):  # 字段 f/t (不是 src/dst), f_port/t_port = out1/in1
```

## 布局常量 (防重叠, 已验证)
- BASE_X=140, COL_W=240, ROW_H=230, BG_H=214
- row_bg: x = BASE_X-160, y = 行y-20, w = (行节点数-1)*240+150+200; h=214
- 普通节点: x = BASE_X + c*COL_W, y = 行y (每行一个 y0/y1/y2/y3)
- 背景名 ≤8 字 (不含 🎨); 节点 x ≥ 背景x+160

## 生成器内嵌校验 (assert, 失败即不落盘)
- 节点 type 全在 NODE_TYPES_OK (14 种)
- 连线 f/t 都在节点 id 集合 (无悬空)
- 每行: min(x) >= bg_x+160 且 相邻 x 差 ≥150

## 模块库挂按钮 (simulink_module.py LIBRARY)
条目加 `"flow": os.path.join(dirname(dirname(dirname(abspath(__file__)))), "flows", "x.json")`
→ 2548 行 `it.get("flow")` 分支自动 load_flow_file, 无需改点击逻辑。
组内可同时放单节点按钮 (左脑/右脑, 默认 add_node_at_center) 和完整模型按钮 (flow 加载)。

## offscreen 验证 (每次改完必跑)
```python
QT_QPA_PLATFORM=offscreen; sys.path.insert(0, GUI)
m = SimulinkModule(); m._sync = lambda: None   # 禁网络同步防卡
ok = m.load_flow_file(FLOW)  # 断言 len(m.nodes)==len(flow["nodes"]) 且 links 同
```
注意: load_flow_file 里 add_node 重新 gen_id → 加载后节点 id ≠ 原 JSON id,
"悬空连线"检查必须用原始 flow 的 id 集合, 别用 m.nodes。

## 对齐真实代码 (老倪"与simulink模型对齐")
flow 节点 params 从真实实现读 (如 LeftRightConfig 的 grasp_d_hp/lift_height/transfer_tolerance/
insert_tolerance, LeftBrainMLP 547K/RightBrainWM 87K), 别手写旧参数;
模块库按钮名/工具栏按钮名与 flow 节点名保持一致 (如 "🧠 左脑 LeftBrainMLP")。

## 与 DAG JSON 导出 (REFERENCE_APPS) 的区别
REFERENCE_APPS 是代码内模板 (load_reference_app_by_name); gen 脚本产物是独立
flows/*.json 文件 (load_flow_file) — 两者格式相同 (nodes/links, f/t), 可互相转换。

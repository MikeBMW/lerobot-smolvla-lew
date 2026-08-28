# Simulink Flow JSON 生成 + 模块库按钮 (2026-08-10)

触发: 把硬件/模型/流程做成 simulink 画布可加载 JSON, 并/或在左侧模块库加按钮。
实例: flows/hardware_toolbox.json (37硬件+5背景行), flows/dual_brain_peg.json (22节点21连线,
left_right 对齐版, 生成器 tools/gui/gen_dual_brain_flow.py), flows/transfer_adaptive.json
(18节点17连线, 实验总结, 生成器 tools/gui/gen_transfer_adaptive_flow.py)。

## flow JSON 格式 (load_flow_file 解析)
```json
{"format":"hermes-flow","version":1,"name":"…","sim":"…",
 "nodes":[{"id":"任意串","type":"…","name":"…","x":…,"y":…,"w":150,
           "icon":"▣","color":"#ff4444","params":{…},
           "inputs":[{"id":"in1","label":"in","dtype":"any"}],
           "outputs":[{"id":"out1","label":"out","dtype":"any"}],"actions":[]}],
 "links":[{"id":"l…","f":"节点id","t":"节点id","f_port":"out1","t_port":"in1","label":"…"}]}
```
- 节点 id 任意字符串; type 必须在 NODE_TYPES: condition/data/model/action/system/hardware/switch/train_gate/yolo_gate/coord_overlay/row_bg/pdf_report/skill/scene
- 连线字段是 f/t (不是 src/dst); label 中文标注链路语义
- icon/color 映射: hardware=▣/#ff4444, model=◈/#58a6ff, condition=❖/#a371f7, system=◉/#d4a800, action=➤/#00d4aa, data=📊/#58a6ff, row_bg=▤/#3a3f4b
- load_flow_file 会重新 gen_id 并 id_map 映射 → 校验"悬空连线"要用加载后 m.nodes, 不能拿原始 JSON 的 id 比
- row_bg 节点额外字段 "h":214; params {bg:"#3a5a3a", model:"行名", desc:…}

## 布局规则 (scene 技能同源坑)
- 行距 230, 列距 240, 节点 y = BASE_Y + r*230, bg y = 节点y-20, bg x = 节点起始x-160
- row_bg 名 ≤8字 (不含🎨); 节点 x ≥ bg.x+160; 行内节点间距 ≥150 (不重叠)
- 生成器脚本幂等: 每次重跑产出同一结构 (可作验证)

## 模块库 LIBRARY 加按钮 (simulink_module.py)
LIBRARY 条目 (ntype, 分组名, [{name, params, …}])。按钮行为分支 (_rebuild):
- it["params"].get("scene_id") → open_scene_link
- it["params"].get("atomic_gate") → open_atomic_skill_flow
- it.get("flow") → load_flow_file(路径)   ← 一键加载完整画布用这个
- it.get("template") → load_reference_app_by_name
- 默认 → add_node_at_center(ntype, name, params)  ← 单个节点按钮用这个
flow 路径用绝对: os.path.join(仓库根, "flows", "xxx.json"), 仓库根 = dirname(dirname(dirname(__file__)))
LIBRARY_SEQ 自动按条目生成序号 (VEH.5.xx) — 无需手动注册; 新分组插入 LIBRARY 任意位置, 序号自动重排

## offscreen 验证模板 (hermes-verify 风格)
```python
os.environ["QT_QPA_PLATFORM"]="offscreen"; sys.path.insert(0, GUI)
from PyQt5.QtWidgets import QApplication; app=QApplication([])
import simulink_module as sm
# 断言 LIBRARY 含按钮名 + LIBRARY_SEQ 注册
m = sm.SimulinkModule(); m._sync = lambda: None   # 禁网络同步防卡
ok = m.load_flow_file(FLOW)
assert ok and len(m.nodes)==exp_n and len(m.links)==exp_l
```
生成器脚本自身也要校验: 类型∈NODE_TYPES / 无悬空连线 / 背景名≤8 / x≥bg+160 / 不重叠

## 坑 (已踩)
- 链条连线 label 列表长度 = 节点数-1, 少一个就 IndexError → 数清楚或加兜底
- 生成器输出路径别落到 tools/flows/ → 仓库根 flows/ 与既有 JSON 同目录
- node_logic 无需注册: 只用 NODE_TYPES 现有类型就不触发 add_node KeyError
- 生成脚本可能被外部 (飞书端/web) 修改 → patch 前 re-read 全文件, 别基于旧视图 patch

## 工具栏按钮 (老倪: "增加按钮，在上边的工具栏" — 不是模块库!)
_build() 里 mk_btn(text, tip, fn, color) + tl.addWidget + 对应 add_xxx() 方法
(内部 add_node_at_center(ntype, name, params))。改完必须 kill-9 重启 studio.py 才生效。

## VEH.5.xx 三套编号体系 (用户报编号对不上名时先反查, 别猜!)
1. 模块库按钮: VEH.5.{LIBRARY_SEQ[name]:03d} — 稳定全局序号 (删条目后重排, 须向用户解释)
2. 画布节点: VEH.5.{lib_seq_of(name):03d}; 名字未注册 → VEH.5.{id%100:02d} 随机回退
3. 工具栏/控件: _veh5_apply() 按位置动态编号 VEH.5.01...
案例: 用户说"删 AWE VEH.5.14", 实际 VEH.5.014=M03 GR00T (AWE 组是 037-042) —
反查: `rev = {v:k for k,v in sm.LIBRARY_SEQ.items()}`; 有歧义用 clarify 一次问清 (删错代价高)

## 模型工程化后同步画布 (left_right 案例, 用户"与simulink模型对齐，重新生成json")
方案 JSON (成绩/架构) → 读真实代码 configuration_*.py + modeling_*.py 的
config 阈值/结构/参数量 → 节点 params 全对齐 (class/结构/params/loss/optimizer/config 值)
→ 生成器重跑 → offscreen 验证 → 重启。模块库按钮名 + 工具栏按钮名同步改。
实例: flows/dual_brain_peg.json v2 (22节点21连线, policy=left_right, 参数对齐 LeftRightConfig)

# 硬件工具箱 → Simulink Flow JSON (2026-08-09)

把「硬件工具箱」所有可控制对象生成一个 simulink 可加载的 flow JSON。
产物: `flows/hardware_toolbox.json` (42节点 = 37 hardware + 5 row_bg, 32连线) + 生成器 `tools/gui/gen_hardware_toolbox_flow.py` (改对象后重跑即再生, 幂等)。

## 对象全集 (与 GUI 代码同源)
- **Z700 关节×14**: `hardware_simulator.py` `Z700_JOINTS` (left_joint_1..6+left_gripper, right_joint_1..6+right_gripper)
- **Z700 相机×7**: `Z700_CAMERAS` (head_3d 1280×720@30 Gemini335L, left/right_wrist 640×480@60, fisheye_0..3 640×480@15)
- **Orin 总线设备×12**: `studio.py` `HardwareToolbox._build_hardware_bus` (三色塔灯/珞石机械臂/电动夹爪/力传感/RealSenseD435/双路急停/扫码枪/触觉TS-F-L/FoundationPose/障碍物检测/状态机/HMI)
- **数字IO×5**: `hardware_simulator.py` `IOState` (急停按钮/塔灯/光栅/扫码枪/夹爪×2)
- **ROS2 节点**: `Z700_ROS2_NODES` sim 8 个 (`/zmax/*`) / real 10 个 (`/tashan/*`, D23 实测)

## flow JSON 格式 (load_flow_file 兼容)
```json
{"format":"hermes-flow","version":1,"name":"...","sim":"...",
 "nodes":[{"id":"任意字符串","type":"hardware","name":"...","x":140,"y":80,"w":150,
           "icon":"▣","color":"#ff4444","params":{...},
           "inputs":[{"id":"in1","label":"in","dtype":"any"}],
           "outputs":[{"id":"out1","label":"out","dtype":"any"}],"actions":[]}],
 "links":[{"id":"...","f":"<from id>","t":"<to id>","f_port":"out1","t_port":"in1","label":"..."}]}
```
- 节点 type 必须在 `simulink_module.py` `NODE_TYPES` (hardware 已存在: ▣ #ff4444); row_bg: ▤ #3a3f4b
- row_bg 节点额外字段: `"h":214`, params `{"bg":"#半透明色","model":"行名","desc":"背景行: 右键改名/改色"}`

## 布局规则 (坑位)
- row_bg 名 ≤8 字 (不含 🎨); 背景 x = 节点起始x - 160; 背景 w = (n-1)×列距 + 150 + 200
- 列距 240, 行距 230 (bg h 214 < 230 不重叠), 节点 y = 行y, bg y = 行y-20
- 节点 x ≥ bg x + 160, 行内节点间距 ≥150 (宽150不重叠)
- 行分组示例: 机械臂(14) / 执行器(4) / 感知(6) / 相机(7) / 安全IO(6)

## 坑: load_flow_file 会重映射 id
`add_node` 用 `gen_id()` 生成新 id, `id_map[spec["id"]]=n["id"]`。加载后 m.nodes 的 id ≠ 原始 JSON id。
校验"无悬空连线"必须对**原始 JSON** 的 links 用原始 nodes id 检查; 对加载后画布断言 `len(m.nodes)/len(m.links)` 与期望一致即可 (add_link 只在两端映射成功时调用, 数量对上即无悬空)。

## offscreen 验证 (无头跑通, 不必开 GUI)
```python
os.environ["QT_QPA_PLATFORM"]="offscreen"
from PyQt5.QtWidgets import QApplication
app=QApplication([])
from simulink_module import SimulinkModule
m=SimulinkModule(); m._sync=lambda:None   # 禁 web POST 同步, 免 comfy mock 超时卡死
ok=m.load_flow_file(FLOW)                 # 断言 ok and 节点/连线数
```
python 用 `/usr/bin/python3` (conda lerobot 环境可能不存在; 系统 PyQt5 可用)。

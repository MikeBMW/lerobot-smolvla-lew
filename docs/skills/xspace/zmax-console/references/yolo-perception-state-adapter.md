# YOLO 感知链 + State Adapter 节点 + 控制台启动 (2026-08-06)

## 控制台启动 (实测踩坑)
- **必须 `/usr/bin/python3`** 启动 (`DISPLAY=:0 /usr/bin/python3 tools/gui/studio.py`) — 系统 python3 带 PyQt5; `.venv`/hermes venv 都没有 (`ModuleNotFoundError: PyQt5`)
- `start.sh` 找 conda lerobot env (本机不存在) 再 fallback 系统 python3
- **`ZMAX_AUTO_RUN=1` 自动演示**: 启动 2.5s 后自动切 Simulink 页 → `open_compare5()` → `start_sim()` 直接运行 (老倪"打开simulink运行"时用)
- "Unknown property cursor" = Qt 无害警告, 忽略
- 重启: kill 旧 → `DISPLAY=:0 ZMAX_AUTO_RUN=1 /usr/bin/python3 tools/gui/studio.py` 后台
- **置顶到桌面前端** (老倪\"看不到窗口\"时): main() 里 `win.show()` 后加 `win.setWindowFlag(Qt.WindowStaysOnTopHint, True)` + `win.raise_()` + `win.activateWindow()` (WSLg 窗口可能被遮挡; wmctrl/xdotool 未装且 sudo 需认证, Qt 内置方案最稳)

## YOLO 感知链 (五模型对比画布最前端, 全部共用)
`📦数据 → 🎯YOLO感知开关(yolo_gate) → 🎯YOLO目标检测 → 📐2D→3D解算 → 🔌State Adapter → 各模型 state 输入`

**老倪架构铁律 (当场纠正)**: **图像直接进各模型视觉 ViT (ResNet18/SmolVLM2/DINOv2/SigLIP), YOLO 只做 state 适配**
- 连线: `(0, 5, "图像")` 数据→视觉主干 直连; `(4, 7, "state39D")` StateAdapter→模型 state 输入
- **绝不把视频流接进 YOLO 链** ("yolo是state适配, 又不是所有视频")

## 新节点接入 (yolo_gate 为例, 漏一个就 KeyError)
1. `NODE_TYPES` (cn/color) — 类型字典
2. `node_logic.py`: `_reg()` 匹配键 + `node_<name>` 函数 (框架动作可复用 `_toggle_train_gate_ctx` 模式)
3. `simulink_ci.py` `NODE_TYPES` 集合
4. 渲染分支 (`elif t == "yolo_gate":` 画 checkbox + "YOLO: 39D 开/3D 关")
5. 画布节点 + 布局行 + LIBRARY 模块库分类 (「🎯 YOLO 3D 检测 (感知)」4 模块: 检测/开关/解算/StateAdapter)

## 连线索引铁律 (插入节点后)
画布节点列表**前部插入节点** → **所有连线索引全错位** (原 0-36 变 0-40), 必须重写整个 links 段 (用旧索引=节点张冠李戴)。布局行按节点名匹配也要同步。列注释与实际行对齐。
**索引核对**: 画布 tuple = `(名称, [节点], [连线], [布局行])`; 连线最大索引+1 = 节点数。改完 ast.parse + 导入 + 数节点/连线数验证。
**五模型→七模型升级 (2026-08-07)**: 加蒸馏 MLP + 官方专家基准两行 → 训练节点 5→7 (`🎓 专家蒸馏训练`/`📏 官方专家基准`), 布局 8 行; 同构模块同列垂直对齐是硬要求 (老倪: "相同的模型放在同样的纵向位置上")。数据源 dims 改 `39D/4D` (peg-v6)。

## 写坏文件恢复
simulink_module.py 被截断/类丢失 (控制台 `cannot import name 'SimulinkModule'`):
1. `git show HEAD~3:tools/gui/simulink_module.py > 文件` 找完整版 (5423 行 vs 截断 1771 行)
2. 恢复后重应用 patch (小改, 别全量 write_file)
3. 验证: `ast.parse` + `import simulink_module` + `hasattr(sm, 'SimulinkModule')` + `wc -l` 对比

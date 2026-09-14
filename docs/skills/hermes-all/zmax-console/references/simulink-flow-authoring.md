# Simulink Flow JSON 生成与画布联动 (2026-08-10 实测)

## 触发
- 把模型/实验/硬件清单做成画布可加载的 JSON ("做成一个json文件, 在simulink画布调用")
- 模块库加按钮 / 画布节点自动训练 / 节点"打开源代码"

## Flow JSON 格式 (load_flow_file 解析)
```json
{"format": "hermes-flow", "version": 1, "name": "...", "sim": "...", 
 "nodes": [{"id": "任意字符串", "type": "必须∈NODE_TYPES", "name": "...", "x": int, "y": int,
            "w": 150, "icon": "▣/◈/➤...", "color": "#hex", "params": {...},
            "inputs": [{"id":"in1","label":"in","dtype":"any"}],
            "outputs": [{"id":"out1","label":"out","dtype":"any"}], "actions": []}],
 "links": [{"id": "...", "f": "源id", "t": "目标id", "f_port":"out1", "t_port":"in1", "label": "..."}]}
```
- 节点 id 加载时被 gen_id() 重映射 (原始 id 任意字符串, 别用原 id 校验加载后节点)
- 类型全集: condition/data/model/action/system/hardware/switch/train_gate/yolo_gate/coord_overlay/row_bg/pdf_report/skill/scene
- 新类型必须注册 NODE_TYPES + COLORS (add_node 用 COLORS[ntype], 缺 → KeyError)

## 生成器模式 (tools/gui/gen_<name>_flow.py, 幂等可重跑)
- 脚本输出 flows/<name>.json + 自带断言 (类型合法/无悬空连线/row_bg 布局)
- row_bg 布局铁律: 背景名 ≤8字; 节点 x ≥ 背景x+160; 列距 240 行距 230 背景高 214;
  节点 y = 行y, 背景 y = 行y-20; bg w = (n-1)*240+150+200
- 每行一个 row_bg 分组, 行内自链/跨行 1-2 条关键线, 别连成蜘蛛网

## 模块库按钮 (simulink_module.py LIBRARY 常量)
- 条目分支: params.scene_id→open_scene_link; params.atomic_gate→open_atomic_skill_flow;
  it["flow"]→load_flow_file; it["template"]→load_reference_app_by_name; 默认→add_node_at_center
- 一键加载画布: {"name": "...", "flow": os.path.join(根, "flows", "x.json"), "params": {...}}
- 删按钮后 LIBRARY_SEQ 序号重排 (删2加1=净-1, 用户可能误以为没删 — 必须解释新编号)
- 画布节点名未注册 LIBRARY_SEQ → 显示 VEH.5.{id%100} 随机尾号 (用户报编号对不上时先查这个)

## ▶ 运行 = 自动训练触发链 (2026-08-10 老倪"我点击运行了, 你要自动启动训练")
- start_sim 检测画布有特征节点 (如 "◉ LeftRightPolicy") → on_train(policy="left_right") → return
- ⚠️ 该检测必须放在 _canvas_stage_nodes() 检查**之前**: 画布含「📄 PDF 报告」节点名会命中
  NODE_RUN_ACTIONS 的 ("PDF", "on_pdf_report") → 走 _start_canvas_flow 而非训练分支
- on_train 加 policy 分支: cfg_path = configs/policies/config_<policy>.yaml (规范位置, 不堆工程根!),
  ts_dir = "<policy>_<时间戳>", pname 显示名; 容器强制 (zmax-std:1.0, --gpus all WSL2)
- config 坑: dataset.episodes: [0] 是占位 → 删掉用全量 (12集3600帧); 否则只训1条轨迹
- _train_gate_state 无开关节点 → 放行 (True), 不用画开关也能训

## node_logic 外部源码映射 (节点"打开源代码"正确姿势)
- 节点逻辑 (node_logic.py 函数, ✏️可修改区) ≠ 真实实现 (src/lerobot/policies/...)
- 三件套: ① _EXTERNAL_LOC[key]=(绝对路径, 行号, "class 真实符号名") ② get_node_location 优先查
  外部映射 ③ get_external_source 按符号行号截取真实源码块 (到下一个顶格 class/def 停)
- 对话框 (node_logic_dialog.py _load_source): 有外部映射 → 显示真实源码只读 (编辑/保存/恢复禁用,
  提示"真实实现·只读参考"), 位置行显示 `📂 文件:行号 · class 真实名` (别显示 node_logic 函数名!)
- ⚠️ _LR_DIR 定位: node_logic.py 在 <root>/tools/gui/ → 仓库根 = dirname ×3 (×2 会指到 tools/src 不存在)
- ⚠️ 只想要"结构说明"类节点 (如 39D obs) 别注册 _EXTERNAL_LOC — 否则对话框显示外部内部源码,
  盖住你要给用户看的结构说明; 不注册外部映射 → 显示 node_logic 函数体 (可编辑)

## WSLg 交互坑
- 右键菜单跑偏到另一屏幕: menu.exec_(mapToGlobal(view_pos)) 多屏错位 → 改 menu.exec_(QCursor.pos())
- WSL 打开视频/文件: UNC (\\wsl.localhost) 被 CMD.EXE 拒绝 ("UNC 路径不支持") → 先复制到
  /mnt/c/Users/Public/ZMAX_videos/ 再 powershell.exe Start-Process 'C:\...' (explorer.exe rc=1 不可靠,
  用 powershell rc=0 + ApplicationFrameHost 进程确认播放器起来)
- 开网页: cmd.exe /c start URL (URL 非 UNC 没问题, 与视频场景区分)

## PDF 报告坑
- 生成器 tools/generate_report.py 输出 "五模型对比技术选型报告_<ts>.pdf", 但 on_pdf_report 和
  _send_report_to_feishu_work 的 glob 写 "Model Zoo技术选型报告_*.pdf" → 永不匹配 → "未找到 PDF"
  → glob 模式必须与生成器实际文件名一致 (grep 生成器输出行确认, 别猜)
- 容器生成文件属主 root → sudo chown 后 GUI/飞书读取才顺

## 验证模式 (每轮改动)
- offscreen: QT_QPA_PLATFORM=offscreen 实例化 SimulinkModule/NodeLogicDialog 断言行为
- 临时脚本: mktemp -t hermes-verify-XXXXXX.py + hermes-verify- 前缀, 跑完 rm
- ⚠️ 断言别查错对象: _show_node_menu 在 SimCanvas 不在 SimulinkModule; 对话框 edit 初始只读是
  防误编辑设计 (点✏️编辑才写), 断言按钮 enabled 而非 isReadOnly

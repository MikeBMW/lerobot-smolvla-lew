# Simulink flow JSON 生成 + 模块库/工具栏按钮维护 (2026-08-10 实战)

## 1. 画布可加载 flow JSON 生成模式 (flows/*.json)
老倪常要求"把这个模型/实验做成 JSON，在 simulink 画布调用"。标准做法 = 生成器脚本：
- `tools/gui/gen_<名>_flow.py`：`add_node(p,i,ntype,name,x,y,params)` + `add_link(f,t,label)` 组装
  nodes/links → `json.dump` 到 `flows/<名>.json`。生成器留库（改对象重跑幂等）。
- 节点类型必须 ∈ `NODE_TYPES` 14 种 (condition/data/model/action/system/hardware/switch/
  train_gate/yolo_gate/coord_overlay/row_bg/pdf_report/skill/scene)，连线字段 f/t。
- 布局规则 (与 zmax-scene-engineering 同源): row_bg 名 ≤8字(去🎨后)、节点 x ≥ 背景x+160、
  列距 240、行距 230、bg 高 214 (y-20)。行内节点间距 ≥150 防重叠。
- 模块库挂按钮: LIBRARY 条目加 `"flow": os.path.join(根, "flows", "xxx.json")` →
  `it.get("flow")` 分支自动 `load_flow_file` 一键加载整张画布。
- 校验: 生成器内 assert (类型合法/无悬空连线/布局坑) + offscreen 真加载
  (`SimulinkModule(); m._sync=lambda:None; m.load_flow_file(...)` 断言节点/连线数)。
- 画布可加"交付行"节点 (▶生成视频 action + 📄PDF报告 pdf_report)，双击可运行，配合对比行连线。

## 2. 模块库 LIBRARY 按钮增删
- `LIBRARY = [(ntype, gname, [items])]`，条目 `{name, params, flow|template}`:
  - `flow` 键 → load_flow_file (一键加载画布)
  - `template` 键 → load_reference_app_by_name
  - 默认 → add_node_at_center (单节点拖入画布)
- 按钮名同步三处: LIBRARY 条目 / 工具栏 mk_btn / add_xxx 方法，改类名(如 左脑MLP→LeftBrainMLP)
  时三处一起改，grep 确认零残留。
- **删按钮后 LIBRARY_SEQ 序号重排** (删N加M净变化): 用户报"VEH.5.xx"时先跑
  `QT_QPA_PLATFORM=offscreen python -c "import simulink_module as sm; rev={v:k for k,v in sm.LIBRARY_SEQ.items()}"`
  反查当前序号，别按旧号猜。删了按钮但用户看到的编号对不上 → 解释重排。
- **删除引用同步**: 已删按钮名若在 ACT_BUILD_STEPS 引导/REFERENCE_APPS 模板里，
  引导步骤必须同步删 (否则卡步)；模板加载用 specs 不受影响；_lib_btns.get 已容错不崩。

## 3. 工具栏按钮增删
- `_build()` 里 `mk_btn(text, tip, fn, color)` + `tl.addWidget`；删 = 删创建行 + 删方法
  (grep 确认无其他引用)。老倪曾要求: 左右脑按钮从工具栏删掉 (入口留模块库)。

## 4. ▶ 运行 = 自动训练 (left_right 工程)
老倪 (2026-08-10): "我点击运行了，你要自动启动训练啊" — 覆盖旧"默认不自动训练"约定。
- `start_sim` 检测画布有 `"◉ LeftRightPolicy"` 节点 → `on_train(policy="left_right")` 自动训练。
- **⚠️ 检测必须放 `_canvas_stage_nodes()` 检查之前**: left_right 画布含「📄 PDF 插拔方案报告」
  节点，名字命中 NODE_RUN_ACTIONS 的 `"PDF"` (kw in name 匹配) → 否则走画布流程分支不训练。
- `on_train` 加 policy 分支三元组: `cfg_path` (configs/policies/config_left_right.yaml) /
  `ts_dir` ("left_right_"+时间戳) / `pname` ("LeftRight")。容器强制 zmax-std:1.0。
- 配置规范位置 **configs/policies/** (老倪: 别堆工程根，根目录已有 64 个历史遗留 config_*.yaml)。
  runtime cfg 仍在根生成 (`config_<policy>_runtime.yaml`，容器内 /app/) 用完即删。

## 5. node_logic 节点注册 + 外部源码定位 (老倪"右键打开源代码不好使")
新画布节点必须注册 node_logic，否则双击/右键打开逻辑时定位不到源码（显示"定位中…"）。
- `node_logic._reg(key, matches, doc, fn)` 最长关键字匹配；节点名要能命中（如 "LeftBrainMLP"）。
- 真实实现在别的文件（如 src/lerobot/policies/left_right/）时:
  `_EXTERNAL_LOC[key] = (abs_path, line, 真实符号名)` — get_node_location 先查它；
  `get_node_external_symbol(key)` 返回符号名。
- **⚠️ NodeLogicDialog 位置行显示坑**: 外部映射必须显示真实符号 `· class LeftBrainMLP`，
  不能显示 node_logic.py 的函数名 `def node_left_brain`（文件:行号与符号名对不上，老倪当场指出）。
- **⚠️ `_LR_DIR` 路径坑**: node_logic.py 在 `<root>/tools/gui/` → 仓库根 = dirname **×3**
  （×2 指向不存在的 tools/src/，os.path.exists 验证时才暴露）。
- 对话框定位不依赖 QDesktopServices/code 命令（WSL 里不好使）——显示 路径:行号 + 📋复制按钮即可。

## 6. 验证模式
- 触发链验证: offscreen 加载 flow → `m.on_train = lambda **kw: called.update(kw)` 防真训练 →
  `m.start_sim()` → 断言 called['policy']=='left_right'。普通画布应不触发。
- 端到端: 容器内冒烟 `_get_policy_cls_from_policy_name('left_right')` 注册 + 参数数；
  然后真跑 `sudo -n docker run --rm --gpus all -v $PWD:/app -w /app -e PYTHONPATH=/app/src
  --entrypoint python zmax-std:1.0 -u -m lerobot.scripts.lerobot_train --config_path /app/config_xxx_runtime.yaml`
  (后台 + notify_on_complete)，产物在 outputs/train/<prefix>_<ts>/checkpoints/。

## 7. NodeLogicDialog 显示真实实现源码 (老倪"代码对不上"第二轮修正)
外部映射节点 (left_right) 对话框**源码区直接显示真实类全文**，不只显示位置行:
- `node_logic.get_external_source(key)`: 读 _EXTERNAL_LOC 文件, 从 line 行截到下一个顶格
  `class / def / @` (或空行后缩进归零), 末尾加 `# ── <符号> 源码结束 (文件:行) ──`。
- NodeLogicDialog._load_source: 有 ext_src → setPlainText(真实源码) + setReadOnly(True) +
  btn_edit/save/restore 全禁用 + hint "🔒 真实实现 · 只读参考" + **return** (否则被
  node_logic 占位函数源码覆盖)。
- 内部节点不受影响 (编辑按钮可用, 初始只读是防误编辑设计)。

## 8. WSLg 打开视频 (老倪"生成的视频看不到")
- ❌ 失败链路: `cmd.exe /c start` + UNC `\\wsl.localhost\...` → CMD 不支持 UNC 当前目录
  + 共享被拒 ("拒绝访问")。explorer.exe 传 UNC 也 rc=1 打不开。
- ✅ 成功链路 (on_insert_video 实测): `shutil.copy2(mp4, "/mnt/c/Users/Public/ZMAX_videos/")`
  → `Popen(["explorer.exe", dst.replace("/mnt/c/","C:\\").replace("/","\\")])`。
- 验证播放器真的起来: `tasklist.exe | grep ApplicationFrameHost` (Win11 UWP"电影和电视"
  宿主进程)。explorer rc=1 不可靠 (单实例转发也可能成功); powershell `Start-Process` rc=0 更明确。

## 9. WSLg 右键菜单跑到另屏 (2026-08-10)
- `menu.exec_(self.viewport().mapToGlobal(view_pos))` 多屏下屏幕归属错位 → 菜单弹到别的屏。
- 修: `menu.exec_(QCursor.pos())` — 跟随系统光标真实位置, 菜单必在鼠标处。
- QMenu 深色 QSS: `QMenu { background:#161b22; color:#e6edf3; border:1px solid #30363d; }`
  `QMenu::item:selected { background:#1f6feb; color:#ffffff; }` 防黑字。

## 10. 训练配置模板坑
- `dataset.episodes: [0]` 是占位 → 必须删掉用全量 (left_right 12集3600帧), 否则只训 1 集
  (且显式 episodes 列表触发 reader bug, 见 zmax-policy-training-eval)。

## 11. PDF 报告 glob 文件名坑 (2026-08-10 "飞书发送: 未找到 PDF 报告文件")
- tools/generate_report.py 实际输出 `reports/五模型对比技术选型报告_<ts>.pdf`
- GUI 曾 glob `"Model Zoo技术选型报告_*.pdf"` → 0 匹配 → 发送端报"未找到"
  (**生成成功 ≠ 发送成功**: 容器 stdout 说"报告已生成"但 glob 模式错 → 发送端找不到)
- 修: glob 必须匹配实际文件名; 容器生成物属主 root (644 可读但建议 chown 防后续 PermissionError)



# VSCode 断点四坑 + YOLO 预热 Qt 线程崩溃 (2026-09-02, v3.4.0)

老倪 6 轮调试排查完整记录。数据源节点断点"进不去"的全部根因与解法，
以及修复过程踩出的新坑（后台线程 import Qt 链 = GUI 启动崩溃）。

## 断点四坑（按排查顺序）

### 坑① 引擎内部断点堵死播放（py-spy 铁证）
- ▶运行 = 先同步跑引擎 `sim.run()`(500步, 含传感器融合 fuse_sensors 等真实源码)
  → 引擎返回后才 `_ss_tick` 逐节点播放(80ms/节点)。
- 在 `src/lerobot/policies/left_right/state_space/*.py`(或 yolo_3d) 设的断点会**先于任何
  节点逻辑命中** → 主线程冻结(debugpy do_wait_suspend) → run() 不返回 → 播放永不开始
  → 数据源等节点断点"永远进不去"。
- 判定: GUI 日志停在引擎阶段(无"⏩ 数据源节点优先"/"▶ 仿真开始")。
- 解法: 删引擎内部断点(只调试节点逻辑时)；想调试引擎就接受每步都停(500步)。
- 修复: `_start_state_space_sim` 数据源节点优先于引擎执行(数据流源头语义)。

### 坑② def/docstring 行断点不命中
- 函数第一条语句是 docstring，def 行无可命中字节码 → debugpy 断点永不触发。
- `_EXTERNAL_LOC` 的 line 参数必须指向**第一行实际代码**(不是 def 行)。
- 指引用户断点设在 for 循环/return 等实际执行行；别设 return None 行(本机有数据时提前 return)。

### 坑③ spec_from_file_location 动态加载的模块断点不绑定（最难查）
- 函数真实执行(日志有输出)但 VSCode 断点不停。
- debugpy/pydevd 对"断点设置时文件未加载"的模块断点不生效：
  import hook 捕获不到 spec_from_file_location 绕过 meta_path 的加载；
  **预加载到 sys.modules 也无用**(同样绕过 import hook)。
- **解法: `exec(compile(src, 真实文件绝对路径, "exec"))` 加载**
  → 函数 co_filename 指向真实文件 → debugpy 按路径查表必命中
  (与引擎 perception/cognition 断点同行为)。
- exec 命名空间必须注入 `{"__file__": 路径, "__name__": ...}`
  (数据层 `_repo_root()` 引用 `__file__` 会 NameError)。

### 坑④ ZMAX_DEBUG_BREAK 强制断点默认移除
- 数据源接真实数据层后，强制断点(debugpy.breakpoint() 按节点名子串)反而先停
  execute_node_logic 造成"没设断点却停了"困惑 → launch.json env 置空，设哪停哪。
- execute_node_logic 的 ZMAX_DEBUG_BREAK 逻辑保留，需要时手动加 env 即恢复。

## 数据源节点接 lerobot 框架真实数据层（三件套）
1. 框架层真实实现文件：`src/lerobot/datasets/metaworld_data_source.py`
   (probe_data_source 按 DATA_ROOTS 优先级真实探测本机训练仓库 info.json 帧/集/特征；
   resolve_source 数据源策略；无 GUI/torch 依赖)。
2. node_logic 节点函数加载真实调用：`exec(compile(src, 真实路径, "exec"))` 保证断点命中。
3. `_EXTERNAL_LOC["data"] = (datasets 文件, 第一行实际代码, "def probe_data_source")`
   → 右键打开+断点进真实文件。

## YOLO 预热 Qt 线程崩溃（修复过程踩出的新坑）
- 背景: 状态空间播放 YOLO 节点真实执行 → _yolo_ensure_aligner 首次加载模型 10-40s
  (主线程同步) → 系统弹 "studio.py is not responding"(正常现象, 点等待勿关闭)。
- **❌ 错误方案(实测 GUI 启动崩)**: 后台线程预热 `_yolo_ensure_aligner(None)` —
  后台线程 import metaworld(gymnasium→cv2 Qt 插件链) → QObject::moveToThread 归属错误
  + debugpy pydevd_file_utils realpath abort → Fatal Python error: Aborted。
  栈: threading.run → _yolo_ensure_aligner → import metaworld → gymnasium → pydevd realpath。
- **✅ 正解(拆两段)**:
  ① 主线程且 **QApplication 创建后** `_yolo_prepare_imports()` import 依赖链
     (yolo_state_aligner + metaworld, `_YOLO_READY` 缓存, 首次几秒)；
  ② 模型构造(YoloStateAligner+env, 纯计算不碰 Qt)放后台线程 `_yolo_ensure_aligner`。
- **通用铁律: 任何 import 链含 Qt 依赖的模块必须在主线程 import, 后台线程只做纯计算**
  (Qt 线程铁律延伸, 同 worker 线程禁 QObject 方法)。

## 诊断工具
- **py-spy (GUI 假死/断点排查第一工具, 别猜别问用户)**:
  `sudo env "PATH=$PATH" ~/lerobot-smolvla-lew/gui-venv311/bin/py-spy dump --pid <gui>`
  (py-spy 装在 gui-venv311, 本机 sudo 免密)。
  - 主线程栈 `do_wait_suspend(pydevd)` = 停在 VSCode 断点
  - 栈 `_yolo_capture`/`node_ss_yolo` = YOLO 真实执行卡住(not responding 正常)
  - 栈 `_start_state_space_sim`/`_ss_tick` = 引擎/节点播放阶段
- **/tmp/simulink_log.txt**: GUI `_log` 落盘, 配合 py-spy 可完整还原执行链
  (运行指令→数据源→引擎→播放→完成 每一步都有日志)。
- 验证环境: offscreen + gui-venv311, `_yolo_prepare_imports` + 后台构造可完整模拟。

## 版本
v3.4.0 落地(老倪验收: "进到断点了")。提交 916d4592→4ef21e5d。

# PyInstaller 打包 importlib 源码 + repo 根路径多候选探测 (2026-08-26 v3.2.2)

## 症状
Windows exe 上跑状态空间仿真引擎(▶运行)报:
`⚠️ 仿真引擎异常: [Errno 2] No such file or directory:
'C:\Users\Admin\AppData\Local\src\lerobot\policies\left_right\state_space\perception.py'`

## 根因一: PyInstaller 收集不到 importlib 按路径加载的文件
state_space_sim.py 用 `importlib.util.spec_from_file_location` 按**文件路径**加载六层源码:
`src/lerobot/policies/left_right/state_space/{perception,parallel,dynamics,cognition,safety,execution,planner}.py`。
PyInstaller 静态分析只跟踪 `import`/`from` 语句, 字符串路径加载的文件**不进 exe**。
之前 v3.2.1 只 add-data 了 flows/ 和 logo.png → exe 里根本没有 perception.py,
frozen 路径逻辑修对了也照样 FileNotFoundError。

**修复 (CI build-win-exe.yml 双平台 + Dockerfile.win)**:
```
--add-data "$GITHUB_WORKSPACE/src/lerobot/policies/left_right;src/lerobot/policies/left_right"
--add-data "$GITHUB_WORKSPACE/src/lerobot/policies/yolo_3d;src/lerobot/policies/yolo_3d"
```
(node_logic.py 的 _EXTERNAL_LOC 也引用 left_right 的 modeling_left_right.py /
configuration_left_right.py 和 yolo_3d 的 yolo_state_aligner.py, 一起打包)

Dockerfile.win 坑: 构建上下文必须从仓库根 (`docker build -f tools/gui/Dockerfile.win .`),
`COPY . /src/` 后 add-data 用相对路径 `"src/lerobot/policies/left_right;..."`;
原注释的 `docker build ... tools/gui/` 上下文只含 tools/gui, src 不在 context 里。

## 根因二: repo 根定位只靠 __file__ 上溯三级
`os.path.dirname(x3, abspath(__file__))` 在以下场景拼错:
- Windows exe (frozen): __file__ 在 AppData 解压目录, 上溯三级 = AppData\Local
  → 拼出 `AppData\Local\src\...` (不存在)
- 绿色版/复制版: tools/gui 被复制到任意位置时同样错

**修复 = 多候选探测 (state_space_sim.py `_find_ss_dir()` / node_logic.py `_node_repo_root()`)**, 顺序:
1. env `ZMAX_REPO_ROOT` (显式指定仓库根, 跨机/绿色版部署兜底)
2. frozen → `sys._MEIPASS` (PyInstaller 解包资源目录, 配合根因一的 add-data)
3. `__file__` 上溯三级 (源码仓库内运行)
4. **向上逐级探测**: 从 `__file__` 所在目录逐级向上找含 `src/lerobot` 的目录
   (tools/gui 被复制到任意位置都能命中仓库根)
5. 全失败 → raise FileNotFoundError 列出**全部已探测路径** + 提示设 ZMAX_REPO_ROOT
   (比裸 [Errno 2] 可诊断)

同批顺手修的同类隐患:
- simulink_module.py:9469 直接用 `_SS_DIR` 但从未定义 (NameError 潜在崩,
  改 `node_logic._SS_DIR`) — 模块级 grep `_SS_DIR` 只在 node_logic.py 有定义,
  simulink_module 是 `import node_logic` 不是 `from ... import _SS_DIR`
- node_logic.py:249/270 行 `repo = dirname(dirname(abspath(__file__)))` —
  dirname×2 指向 tools/ 而非仓库根 (拼 `tools/distill_expert.py` 会错), 改 `_REPO_ROOT`

## 验证 (全部真实执行)
- Linux 源码模式: `gui-venv311/bin/python state_space_sim.py` → 完成 True,
  11 阶段序列, 残差峰值 0.7192, 接触概率 0.997
- 模拟 frozen: `sys.frozen=True; sys._MEIPASS=仓库根` → _SS_DIR 命中 _MEIPASS
- env: `ZMAX_REPO_ROOT=仓库根` → 命中
- 复制到 /tmp (无仓库): 报清晰错误列出已探测路径 (符合预期)
- node_logic + simulink_module + state_space_sim 三模块全量导入 OK
- `_DATASET_DIR` 也要从 _SS_DIR 上溯 5 级 (state_space→left_right→policies→lerobot→src→根),
  不是从 __file__ 算

## 版本同步
v3.2.2: studio.py (QLabel + setWindowTitle 注释) / update_checker.py CURRENT_VERSION /
version_sync.py zmax_ver / docs_sync.py ver dict / VERSION.md 历史表 — 五处同步。

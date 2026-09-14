# Frozen exe 运行时路径与黑屏排查（Windows/macOS, 2026-08~09 实测）

PyInstaller frozen 产物与源码运行差异巨大，GUI 用户报"黑屏/加载失败"时按此排查。

## 1. frozen __file__ 指向解压目录 → 上溯路径错（最常见根因）

| 平台 | frozen 时 __file__ 实际位置 | 拼错的典型报错 |
|---|---|---|
| Windows --onefile | %TEMP% 解压 或 AppData 目录 | `C:\Users\<u>\AppData\Local\src\...` FileNotFoundError |
| macOS .app | `App.app/Contents/Frameworks` | `/Applications/App.app/Contents/Frameworks/tools` 不存在 |
| 源码 | 仓库内 | （正常） |

**触发**：任何 `os.path.dirname(__file__)` 上溯 N 级定位仓库资源（flows/、src/...、tools/、reports/）的代码，frozen 下全部错位。动态 importlib 加载的源码目录（非 import 依赖，PyInstaller 不收集）尤其容易踩。

**修复模式** — 多候选探测函数，找到含标记文件的那个：
```python
def _resolve_dir():
    rel = os.path.join("src", "...", "state_space")   # 目标相对仓库根的路径
    cands = []
    _env = os.environ.get("ZMAX_REPO_ROOT")            # ① 显式环境变量（跨机/容器最可靠）
    if _env and os.path.isdir(_env): cands.append(os.path.join(_env, rel))
    if getattr(sys, "frozen", False):                  # ② frozen → _MEIPASS
        cands.append(os.path.join(getattr(sys, "_MEIPASS", ""), rel))
    cands.append(os.path.join(dirname(dirname(dirname(abspath(__file__)))), rel))  # ③ 源码上溯
    d = dirname(abspath(__file__))                     # ④ 逐级向上找仓库根（tools/gui 被复制到任意处也有效）
    while True:
        cands.append(os.path.join(d, rel))
        if os.path.dirname(d) == d: break
        d = os.path.dirname(d)
    for c in cands:
        if os.path.isfile(os.path.join(c, "perception.py")):   # 标记文件
            return c
    raise FileNotFoundError("未找到(已探测: " + "; ".join(dict.fromkeys(cands)) + ")")
```
启动脚本 export `ZMAX_REPO_ROOT=<repo>` 即显式兜底。

## 2. exe 无法做的重负载 → frozen 守卫 + 友好提示

视频生成/训练类功能依赖 `.venv/bin/python` + GPU 渲染，exe 里不存在 → 裸报 FileNotFoundError。
```python
if getattr(sys, "frozen", False):
    return False, "exe 版无法本地生成视频(需 .venv + GPU) — 请在 4060/ECS 生成后放回"
```

## 3. 资源名不匹配（视频找不到）

代码 glob `*MLP*.mp4` 或找 `insert_success_demo.mp4`，但 CI 只打包了 `mlp_insert_success_final.mp4` → 用户报"无视频"。frozen 分支用候选名列表逐个找，且 glob 目录要对 _MEIPASS（打包时 --add-data 进 `reports` 的相对路径）。

## 4. "运行后黑屏 / 返回主页面" = 置顶窗口盖画布 或 崩溃

- **自动弹出的置顶窗口**（`Qt.WindowStaysOnTopHint`，设计为防被视频窗遮挡）会盖住主画布 → 用户描述"画布黑屏/不见了"。修法：`__init__(self, ..., on_top=True)` 参数，**手动点按钮打开=置顶，运行后自动打开=on_top=False**；更稳的是运行后干脆不自动弹，改手动按钮。
- **崩溃（先黑屏后回主页）**：MDI/stack 页面被关 = 子窗口崩溃。跨线程 QObject、渲染子进程抢占都可能。诊断用**构造阶段打点**（写文件而非 GUI log）：
```python
# /tmp/zmax_simulink_init.log
_mk = lambda m: open("/tmp/zmax_simulink_init.log","a").write(f"{time.time():.1f} {m}\n")
_mk("START"); sim = SimulinkModule(); _mk("post-construct")
```
缺哪行 = 崩在哪段。本机 offscreen 构造 OK ≠ 目标平台 OK（Mac cocoa/OpenGL 差异）。

## 5. macOS 黑屏 — OpenGL 软件渲染兜底 + .command 启动器

3D 视图（GLViewWidget/pyqtgraph）在 Mac 上 OpenGL 上下文失败 → 窗口黑。启动器模式：
```bash
export QT_OPENGL=software          # desktop→黑屏时换 software，绝不黑但 3D 慢
export LIBGL_ALWAYS_SOFTWARE=1
unset QT_SCALE_FACTOR              # Retina 必须，禁手设缩放
export ZMAX_REPO_ROOT="$REPO"
# 找 python: gui-venv311/bin > .venv/bin > 系统 python3
"$PY" tools/gui/studio.py 2>&1 | tee ~/zmax_console.log   # 黑屏看日志尾部
```
做成 `启动XXX_mac.command`（chmod +x 双击跑）+ 桌面快捷方式，绕开 exe 渲染问题且留诊断日志。

## 6. 判断顺序（用户报 exe 黑屏/加载失败时）

1. **版本**：修复是否在用户跑的 tag 之后？（git log tag vs commit 时间）—— 90% 是跑旧 exe
2. frozen 路径探测是否覆盖（_MEIPASS / env / 上溯）
3. 资源是否 --add-data 打进去 + 名字匹配
4. 置顶窗口/自动弹窗是否盖画布
5. OpenGL 兜底（QT_OPENGL=software）

# Frozen 路径多候选探测 (2026-08-26 v3.2.2-v3.2.5 实测)

**坑**: PyInstaller exe 运行时 `__file__` 指向解压目录 (Windows `AppData\Local\...`, Mac `Contents/Frameworks`),
`__file__` 上溯三级拼相对路径 → `C:\Users\Admin\AppData\Local\src\...` / `/Applications/Z-MAX_Console.app/Contents/Frameworks/tools` 不存在 → FileNotFoundError。
**任何用 `__file__` 上溯定位仓库资源/动态加载 .py 的代码, exe 下必炸。**

## 修复模式 (多候选探测, 找到含标志文件为止)

```python
def _find_dir(rel, marker):
    cands = []
    env = os.environ.get("ZMAX_REPO_ROOT")          # ① env 显式指定
    if env and os.path.isdir(env):
        cands.append(os.path.join(env, rel))
    if getattr(sys, "frozen", False):
        cands.append(os.path.join(getattr(sys, "_MEIPASS", ""), rel))  # ② _MEIPASS
    cands.append(os.path.join(                          # ③ __file__ 上溯三级 (源码)
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), rel))
    d = os.path.dirname(os.path.abspath(__file__))      # ④ 逐级向上探测仓库根
    while True:
        cands.append(os.path.join(d, rel))
        parent = os.path.dirname(d)
        if parent == d: break
        d = parent
    for c in cands:
        if os.path.isfile(os.path.join(c, marker)):
            return c
    raise FileNotFoundError(f"未找到 {marker} (已探测: {'; '.join(dict.fromkeys(cands))})")
```

- 标志文件选稳定存在的 (如 `perception.py`、目录存在性)
- `ZMAX_REPO_ROOT` env 兜底: Linux/跨机部署显式指定仓库根
- **importlib 动态加载的 .py 不会被 PyInstaller 自动收集** → 打包必须 `--add-data` 含整个源码目录 (如 `src/lerobot/policies/left_right`)

## exe 运行时其他坑 (同批次实测)

- 无 `.venv`/GPU → 视频生成等重负载功能 frozen 守卫跳过, 提示"需 4060/ECS 生成后放回" (`if getattr(sys,"frozen",False): return False, "..."`)
- 运行后自动弹出的窗口 (3D 视图等) 若 `WindowStaysOnTopHint` 置顶 → **盖住主界面看起来黑屏** → 自动弹出用 `on_top=False`, 手动点按钮才置顶
- Mac 无 GPU/EGL → metaworld 渲染子进程跳过 (`sys.platform == "darwin"`)
- exe 内置视频名与代码查找名不一致 → frozen 分支优先找打包名 (`mlp_insert_success_final.mp4` 等), 再 fallback 源码名

## Mac 黑屏诊断法

用户报"启动后黑屏返回主页"时: 在构造函数关键段写文件打点
(`/tmp/zmax_simulink_init.log`: START → pre-_build → post-_build), 缺失哪行 = 崩在哪段,
不依赖 GUI 就能定位构造崩溃点。源码模式启动脚本应带 `QT_OPENGL=software` +
`LIBGL_ALWAYS_SOFTWARE=1` 兜底 (3D GLViewWidget 在 Mac OpenGL 上下文失败会黑屏)。

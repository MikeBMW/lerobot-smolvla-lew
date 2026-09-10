# Z-MAX Console macOS 反复重启 — 根因诊断与修复清单

> 版本: v5.5.11 · 诊断: 小芳 (Mac 实测) · 2026-09-10
> 现象: 点击「▶ 运行」→ app 重启（新实例弹出）

## 一、根因（Mac 实测确认）

### 🎯 根因 1（致命）: `sys.executable` 被当作 python 解释器
```python
# simulink_module.py (5 处)
r = _sp.run([sys.executable, os.path.join(root, "tools", "gen_l4_demo_video.py"), ...])
```
**PyInstaller 打包后 `sys.executable` = app 二进制自身**
(`/Applications/Z-MAX_Console.app/Contents/MacOS/Z-MAX_Console`)

→ 子进程调用 = 再次启动 app 二进制
→ bootloader 忽略脚本参数, 重新初始化并跑 studio.py
→ **表现为「点击运行就重启」**（其实是 app 自己又启动了一遍）

### 🎯 根因 2: `MUJOCO_GL="egl"` 在 macOS 不可用
```python
env={**os.environ, "MUJOCO_GL": "egl"}   # macOS 不支持 egl
```
macOS 只支持 `glfw`（或 osmesa）。egl → MuJoCo 渲染崩溃。

### 🎯 根因 3: `gui-venv311` 硬编码路径
```python
py = os.path.join(root, "gui-venv311", "bin", "python")   # WSL/4060 开发环境路径
MW_ASSETS = os.path.expanduser("~/lerobot-smolvla-lew/gui-venv311/lib/python3.11/site-packages/metaworld/assets")
```
macOS 上不存在 → 找不到 python / 找不到 metaworld 场景 xml。

### ⚠️ 根因 4: PYZ 优先导致热修无效
PyInstaller 把 `simulink_module.py`/`node_logic.py`/`studio.py` 编译进 **PYZ**，
运行时 **FrozenImporter 优先于文件系统** → 直接改 app 内的 .py 文件**不生效**。
（只有 PYZ 里**没有**的模块，如 node_logic 首次缺失时，复制 .py 才生效）
→ **必须改源码重新打包，不能靠热修**。

### ⚠️ 根因 5: 打包缺失依赖
v5.5.11 的 app 内**没有**:
- `ultralytics`（YOLO 检测, node_logic.py 直接 import）
- `torch`（ultralytics 必需）
- `gymnasium` / `imageio`（metaworld 依赖链）
- `glfw` / `libglfw.3.dylib`（MuJoCo 渲染后端）

日志实证:
```
ModuleNotFoundError: No module named 'ultralytics'
  File ".../node_logic.py", line 1400, in _yolo_ensure_aligner
```

## 二、修复清单（打包前必须改）

### A. 代码层（simulink_module.py）
```python
# ① 跨平台真 python (PyInstaller frozen 环境)
def _real_python():
    if getattr(sys, "frozen", False):
        cands = [
            os.environ.get("ZMAX_PYTHON"),
            os.path.join(os.path.expanduser("~"), ".zmax", "pyenv", "bin", "python"),
            "/opt/homebrew/bin/python3",
            "/usr/bin/python3",
        ]
        for c in cands:
            if c and os.path.exists(c):
                return c
    return sys.executable
_PY = _real_python()
# 5 处: [sys.executable, ...] → [_PY, ...]

# ② 跨平台渲染后端
_MGL = "glfw" if sys.platform == "darwin" else "egl"
env = {**os.environ, "MUJOCO_GL": _MGL}   # 2 处

# ③ 去掉 gui-venv311 硬编码 → 用 sys.executable / 打包内路径
```

### B. 打包层（.github/workflows/build-win-exe.yml）
```yaml
# Install dependencies 增加
pip install ultralytics gymnasium imageio glfw

# PyInstaller collect 增加
--collect-all ultralytics
--collect-all gymnasium
--collect-all imageio
--collect-all glfw
# (metaworld/mujoco/scipy 已有)

# --add-data 增加
--add-data "tools:tools"
--add-data "tools/gen_l4_demo_video.py:."
--add-data "tools/gen_l4_demo_scene.py:."
```

### C. Metaworld 场景 xml（L4 定制场景）
`gen_l4_demo_scene.py` 生成 `sawyer_peg_insertion_side_l4.xml` 写入 metaworld assets。
打包时需**预生成并包含**，或运行时首启自动生成。

## 三、Mac 端临时验证结果（证明物理引擎本身没问题）
命令行按 app 调用方式执行成功：
```
MUJOCO_GL=glfw ./gui-venv311/bin/python tools/gen_l4_demo_video.py --also-latest
→ 8 阶段全通: 转台90°干扰 → 绕z抓横 → 治具校直 → 标准抓取
              → 插入 49.5mm → 拔出 53mm → AOI 悬停 → 光耦合 η=1.0
→ 视频 1624 帧
```
**说明**: 引擎/场景/脚本都正常, 问题纯在 **app 打包与代码的 macOS 适配**。

## 四、结论
| 层 | 状态 |
|:---|:---|
| 物理引擎/脚本 | ✅ 正常（命令行验证通过）|
| app 代码（sys.executable / egl / gui-venv311）| ❌ 需改 |
| 打包依赖（ultralytics/torch/glfw 等）| ❌ 需补 |
| PYZ 热修 | ❌ 无效，必须重打包 |

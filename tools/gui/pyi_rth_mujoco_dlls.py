"""PyInstaller 运行时钩子 — 修 mujoco 自带插件 DLL 在 frozen 包里的加载问题。

现象 (2026-09-15, 老倪 Windows exe v5.6.4, 点「🎥 真实化运行」即崩):
    import mujoco → mujoco/__init__.py::_load_all_bundled_plugins()
    → ctypes.CDLL("<_MEIPASS>\\mujoco\\plugin\\actuator.dll")
    → "Failed to load dynlib/dll '...\\mujoco\\plugin\\actuator.dll'.
       Most likely this dynlib/dll was not found when the application was frozen."

根因 (PyInstaller archive_viewer + pefile + CI 冻结核验实测, 不是猜):
    ① 布局: PyInstaller 把 mujoco 运行时库放 `_MEIPASS/mujoco/mujoco.dll`, 插件放
       `_MEIPASS/mujoco/plugin/*.dll`; 而 actuator.dll 的 PE 导入表依赖 `mujoco.dll`
       (+VCRUNTIME140/MSVCP140)。Windows 解析 DLL 依赖只看「DLL 自身目录 + 已注册搜索目录」,
       plugin/ 里没有 → 加载失败; PyInstaller 的 ctypes 钩子 (loader/pyimod03_ctypes.py)
       把底层 OSError 包成上面那句, **真正的 cause 只在 e.__cause__ 里** (实测 CI 里是
       WinError 1114 / DLL initialization routine failed, 在真机上也可能是 126)。
    ② 结论: frozen 环境里这几个引擎插件 DLL 能不能起来, 与打包环境强相关 —— 所以本钩子不硬编码
       "装一份依赖就完事", 而是**逐级修 + 逐级实测, 修不动就显式降级**, 并把结论写进环境变量留证。

做法 (本钩子在主脚本之前运行 → 早于 import mujoco):
    阶段 0: 注册 _MEIPASS / _MEIPASS/mujoco / _MEIPASS/mujoco/plugin 到 DLL 搜索目录 + PATH;
    阶段 1: 若插件仍 load 不了 → 把 `mujoco.dll` 复制进 plugin/ (让插件目录自足);
    阶段 2: 再把 VCRUNTIME140*/MSVCP140* 复制进 plugin/;
    阶段 3: 仍 load 不了的插件 → 改名 `*.dll.zmax-off` 显式停用 (mujoco 的
            _load_all_bundled_plugins 只扫 .dll/.so/.dylib → 就不会再去 load)。
    ✅ 停用是安全的: 本产品全部场景 (metaworld stock + 我们的 L4 干扰场景 XML) 都不引用
       <plugin>, 实测 grep 全库/全 metaworld assets 命中 0; 老倪要的是"点运行能跑"。
       结论与阶段写入 ZMAX_MUJOCO_DLL_FIX, 冻结核验 (studio.py --engine-selftest) 会打印出来。
非 Windows / 非 frozen 直接 return → 源码运行与 macOS 行为不变; 全部文件来自包内, 不联网。
"""

import ctypes
import glob
import os
import shutil
import sys

_CRT = ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll", "msvcp140_1.dll")


def _pi_note(**kw):
    os.environ["ZMAX_MUJOCO_DLL_FIX"] = ",".join(f"{k}={v}" for k, v in kw.items())


def _pi_try_load(path):
    try:
        ctypes.CDLL(path)
        return True
    except Exception:
        return False


def _pi_copy(pattern_dirs, plugin, names):
    copied = []
    for root in pattern_dirs:
        if not os.path.isdir(root):
            continue
        for name in names:
            src, dst = os.path.join(root, name), os.path.join(plugin, name)
            if os.path.isfile(src) and not os.path.exists(dst):
                try:
                    shutil.copy2(src, dst)
                    copied.append(name)
                except Exception:
                    pass
        for cand in glob.glob(os.path.join(root, "mujoco*.dll")):
            dst = os.path.join(plugin, os.path.basename(cand))
            if not os.path.exists(dst):
                try:
                    shutil.copy2(cand, dst)
                    copied.append(os.path.basename(cand))
                except Exception:
                    pass
    return copied


def _pi_install_mujoco_dll_dirs():
    if not getattr(sys, "frozen", False) or not sys.platform.startswith("win"):
        return
    base = getattr(sys, "_MEIPASS", "") or ""
    if not base:
        return
    mj = os.path.join(base, "mujoco")
    plugin = os.path.join(mj, "plugin")
    if not os.path.isdir(plugin):
        _pi_note(stage="no_plugin_dir")
        return
    dirs = [base, mj, plugin]
    add_dir = getattr(os, "add_dll_directory", None)
    if callable(add_dir):
        for d in dirs:
            if os.path.isdir(d):
                try:
                    add_dir(d)
                except Exception:
                    pass
    os.environ["PATH"] = os.pathsep.join([d for d in dirs if os.path.isdir(d)] + [os.environ.get("PATH", "")])

    plugs = sorted(glob.glob(os.path.join(plugin, "*.dll")))
    if not plugs:
        _pi_note(stage="no_plugins")
        return
    # 阶段 0/1/2: 逐级补依赖, 每级都实测 (load 成功 = 该级够用)
    if all(_pi_try_load(p) for p in plugs):
        _pi_note(stage="dirs_only", n=len(plugs))
        return
    got = _pi_copy([base, mj], plugin, ())
    if got and all(_pi_try_load(p) for p in plugs):
        _pi_note(stage="copy_mujoco", copied="|".join(got))
        return
    got2 = _pi_copy([base, os.path.join(base, "PyQt5", "Qt5", "bin")], plugin, _CRT)
    if all(_pi_try_load(p) for p in plugs):
        _pi_note(stage="copy_crt", copied="|".join(got + got2))
        return
    # 阶段 3: 修不动 → 显式停用 (本产品不用引擎插件; 留证 + 不让 import mujoco 崩)
    off = []
    for p in plugs:
        if not _pi_try_load(p):
            try:
                os.rename(p, p + ".zmax-off")
                off.append(os.path.basename(p))
            except Exception:
                pass
    _pi_note(stage="disabled", copied="|".join(got + got2), off="|".join(off))


try:
    _pi_install_mujoco_dll_dirs()
except Exception as _pi_e:  # 钩子自身绝不能把 app 拖崩
    try:
        _pi_note(stage=f"hook_error:{type(_pi_e).__name__}")
    except Exception:
        pass

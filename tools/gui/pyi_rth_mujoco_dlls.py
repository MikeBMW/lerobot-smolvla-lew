"""PyInstaller 运行时钩子 — 修 mujoco 插件 DLL 在 frozen 包里的依赖解析。

现象 (2026-09-15, 老倪 Windows exe v5.6.4, 点「🎥 真实化运行」):
    import mujoco → mujoco/__init__.py::_load_all_bundled_plugins()
    → ctypes.CDLL("<_MEIPASS>\\mujoco\\plugin\\actuator.dll")
    → "Failed to load dynlib/dll '...\\mujoco\\plugin\\actuator.dll'.
       Most likely this dynlib/dll was not found when the application was frozen."

根因 (用 PyInstaller archive_viewer + pefile 反查 v5.6.4 exe 实测, 不是猜):
    exe 内实际布局:
        mujoco\\mujoco.dll           ← 运行时库, 在 mujoco/ 这一级
        mujoco\\plugin\\actuator.dll  ← mujoco 自带插件, 在下一级
        VCRUNTIME140.dll (顶层) / PyQt5\\Qt5\\bin\\MSVCP140.dll
    actuator.dll 的 PE 导入表写的是 **mujoco.dll** 且需要 VCRUNTIME140/MSVCP140(pefile 实测),
    而 Windows 解析「DLL 依赖」时只查 DLL 自身目录 + 进程搜索目录 —— plugin\\ 里没有 mujoco.dll,
    MSVCP140 又只在 PyQt5\\Qt5\\bin 下 → WinError 126; PyInstaller 的 ctypes 钩子
    (loader/pyimod03_ctypes.py) 把底层 OSError 包装成上面那句 "not found when frozen", 真相被盖住。

修法 (本钩子在主脚本之前执行, 因此早于 import mujoco):
    ① 主修: 把 plugin/ 目录做成自足目录 —— 从包内各处找到 mujoco.dll / VCRUNTIME140* / MSVCP140*
       复制一份到 mujoco/plugin/ (DLL 自身目录必然参与依赖解析, 不依赖搜索路径策略);
    ② 次要: 注册 _MEIPASS、_MEIPASS/mujoco、_MEIPASS/mujoco/plugin 到 DLL 搜索目录 + PATH。
非 Windows / 非 frozen 直接返回 → 源码运行与 macOS 行为完全不变。文件都是包内既有文件, 不联网。
"""

import glob
import os
import shutil
import sys

# 插件 DLL 真正需要的依赖 (mujoco.dll 来自 mujoco 包, 其余来自 VC 运行时)
_PI_WANTED = ("mujoco.dll", "vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll", "msvcp140_1.dll")


def _pi_install_mujoco_dll_dirs():
    if not getattr(sys, "frozen", False) or not sys.platform.startswith("win"):
        return
    base = getattr(sys, "_MEIPASS", "") or ""
    if not base:
        return
    mj = os.path.join(base, "mujoco")
    plugin = os.path.join(mj, "plugin")
    if not os.path.isdir(plugin):
        return
    # ① 自足化 plugin 目录 (主修)
    search_roots = [base, mj, os.path.join(base, "PyQt5", "Qt5", "bin")]
    copied = []
    try:
        for root in search_roots:
            if not os.path.isdir(root):
                continue
            for name in _PI_WANTED:
                src = os.path.join(root, name)
                dst = os.path.join(plugin, name)
                if os.path.isfile(src) and not os.path.exists(dst):
                    shutil.copy2(src, dst)
                    copied.append(name)
            # 大小写/版本号变体兜底 (如 mujoco.3.3.0.dll)
            for cand in glob.glob(os.path.join(root, "mujoco*.dll")):
                c_dst = os.path.join(plugin, os.path.basename(cand))
                if not os.path.exists(c_dst):
                    shutil.copy2(cand, c_dst)
                    copied.append(os.path.basename(cand))
    except Exception:
        pass
    # ② 注册搜索目录 (次要; 某些加载路径不受 ① 覆盖时兜底)
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
    os.environ["ZMAX_MUJOCO_DLL_FIX"] = "copied=" + ",".join(copied)


_pi_install_mujoco_dll_dirs()

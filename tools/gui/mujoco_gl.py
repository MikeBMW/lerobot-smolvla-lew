"""🎮 MuJoCo 渲染后端自动选择 (2026-09-10 老倪: mac 报 Failed to load GLFW3 shared library)

问题: 代码硬编码 MUJOCO_GL=glfw → macOS 无 GLFW3 共享库 → 真实化运行失败
      (Windows 同样缺 GLFW DLL)

方案: 按平台选自带的原生离屏后端 (mujoco 官方支持, 无需额外系统库):
      macOS   → cgl   (CoreGL, 系统自带)
      Windows → wgl   (系统自带)
      Linux   → egl (无头/服务器) / glfw (有桌面)
用户已设 MUJOCO_GL 则尊重 (如采集脚本显式指定 egl)。
"""
import os
import sys


def pick_mujoco_gl(default_linux: str = "glfw") -> str:
    """返回本平台可用的 MuJoCo 渲染后端名。"""
    cur = os.environ.get("MUJOCO_GL")
    if cur:
        return cur
    if sys.platform == "darwin":
        return "cgl"
    if sys.platform == "win32":
        return "wgl"
    return default_linux


def setup_mujoco_gl(default_linux: str = "glfw") -> str:
    """若未设置则写入平台合适的 MUJOCO_GL 并返回。"""
    gl = pick_mujoco_gl(default_linux)
    os.environ.setdefault("MUJOCO_GL", gl)
    return gl

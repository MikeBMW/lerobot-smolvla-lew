"""🐍 运行时 Python 解释器解析 (2026-09-10 mac app 反复重启根因根治)

问题: PyInstaller 打包后 `sys.executable` = **app 二进制本身**。
     GUI 用它启动 python 子进程 (gen_l4_demo_video / cicd_deploy / validate_flow 等)
     → 每次点"运行"实际启动了一个**新的 app 实例** → 表现为"反复重启"。
     (PYZ 内代码优先于外部 .py, 本地热修无效 — mac 实测确诊)

方案: frozen 环境下不返回 sys.executable, 而是找一个**真正的解释器**:
      1) PATH 里的 python3 / python
      2) macOS/Linux 常见绝对路径
      3) 兜底返回 "python3" (让系统报清晰的 not found, 而不是静默重启 app)
     源码环境 (未打包) 行为不变: 返回 sys.executable。
"""
import os
import shutil
import sys

_CANDIDATES = (
    "python3",
    "python",
    "/usr/local/bin/python3",       # macOS Intel / brew
    "/opt/homebrew/bin/python3",    # macOS Apple Silicon / brew
    "/usr/bin/python3",             # macOS system / Linux
)


def resolve_python() -> str:
    """返回可用于启动 python 子进程的解释器路径。"""
    if not getattr(sys, "frozen", False):
        return sys.executable
    for name in _CANDIDATES:
        p = shutil.which(name) if not name.startswith("/") else (name if os.path.exists(name) else None)
        if p:
            return p
    # 兜底: app 同目录下可能有 bundled python (未来扩展)
    exe_dir = os.path.dirname(sys.executable)
    for name in ("python3", "python"):
        p = os.path.join(exe_dir, name)
        if os.path.exists(p):
            return p
    return "python3"

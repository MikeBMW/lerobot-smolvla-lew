"""
Z-MAX 更新检查模块
检测 GitHub Release 新版本，支持自动升级
"""

import os, sys, json, urllib.request, threading, time

REPO = "MikeBMW/lerobot-smolvla-lew"
API_RELEASES = f"https://api.github.com/repos/{REPO}/releases/latest"
CURRENT_VERSION = "v2.2.0"


def get_current_version():
    """返回当前版本号"""
    return CURRENT_VERSION


def get_local_version_file():
    """版本标识文件（放在 .exe 同级，标记已安装版本）"""
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        return os.path.join(exe_dir, ".zmax_version")
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".zmax_version")


def check_latest(timeout=8):
    """检查 GitHub 最新 Release 版本"""
    try:
        req = urllib.request.Request(API_RELEASES, headers={
            "User-Agent": "ZMAX-Console/1.0",
            "Accept": "application/vnd.github.v3+json",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except Exception:
        return None

    tag = data.get("tag_name", "")
    if not tag:
        return None

    # 找 .exe 下载链接
    download_url = ""
    for asset in data.get("assets", []):
        if asset["name"].endswith(".exe"):
            download_url = asset["browser_download_url"]
            break

    return {
        "version": tag,
        "download_url": download_url,
        "release_url": data.get("html_url", ""),
        "published": data.get("published_at", ""),
        "body": (data.get("body") or "")[:200],
    }


def check_in_background(callback):
    """后台线程检查更新"""
    def _run():
        info = check_latest()
        if info and info["version"] != CURRENT_VERSION:
            callback(info)
    threading.Thread(target=_run, daemon=True).start()


def download_update(download_url, save_path, progress_callback=None):
    """下载新版本 .exe 到指定路径"""
    try:
        req = urllib.request.Request(download_url, headers={
            "User-Agent": "ZMAX-Console/1.0",
        })
        with urllib.request.urlopen(req, timeout=120) as resp:
            total = int(resp.headers.get("content-length", 0))
            downloaded = 0
            chunk_size = 8192
            with open(save_path, "wb") as f:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and total:
                        progress_callback(int(downloaded * 100 / total))
        return True
    except Exception as e:
        return False

# 新家容器首启坑 (2026-08-15 实测, Docker Desktop 环境)

## 环境: 新家 = 纯 Docker Desktop 容器 (192.168.65.x)

- 无 /mnt/wslg、无 WSL interop (无 powershell.exe)、无 docker.sock、无 /mnt/c
- Windows 宿主可达: `host.docker.internal` = 192.168.65.254 (445 通)
- 显示唯一通道 = Windows 宿主 VcXsrv (必须 `-ac` 允许远程), 容器 DISPLAY=host.docker.internal:0
- 用户已明确: **以后不用 WSL** (旧家 WSLg / vcxsrv_watch.sh 那套作废)
- 探测 X: `timeout 2 bash -c 'echo > /dev/tcp/host.docker.internal/6000' && echo UP`
- 容器无法替用户启动 Windows 程序 (无 interop/ssh/docker.sock) → VcXsrv 需用户在 Windows 上开:
  `"C:\Program Files\VcXsrv\vcxsrv.exe" :0 -ac -multiwindow -clipboard` (Win+R, 防火墙放 6000)

## 坑 1: GUI 全无汉字 (老倪"没有汉字,修")

容器默认只有 ~8 个英文字体, `fc-list :lang=zh` 为空 → Qt 中文全变方块。
修复: `apt-get install -y fonts-wqy-microhei fonts-wqy-zenhei`, 装完
`fc-list :lang=zh` 出现 WenQuanYi 即好, **重启 studio.py 生效** (不用动代码)。

## 坑 2: xcb 插件加载失败

`qt.qpa.plugin: Could not load the Qt platform plugin "xcb"` → 容器缺 X11 客户端库:
```
apt-get install -y libxcb-xinerama0 libxcb-icccm4 libxcb-keysyms1 libxcb-image0 libxcb-randr0 \
  libxcb-render-util0 libxcb-shape0 libxcb-xkb1 libxkbcommon-x11-0 libxkbcommon0 libgl1 libegl1 \
  libxcb-cursor0 libxcomposite1 libxdamage1 libxfixes3 libxrender1 libxtst6 libxi6
```

## 坑 3: 启动左上角黑色阴影闪动 (老倪"左上角有黑色阴影闪动")

VcXsrv -multiwindow 下窗口首帧映射先落 Windows 默认位(左上)再跳 setGeometry 目标位 →
深色主题窗口在左上角闪现。修复在 studio.py main():
`win.show()` 后加 `QTimer.singleShot` 多次强制回位 — **单次 singleShot(0) 不够**
(窗口映射与首帧绘制之间有延迟, 映射后还会再跳一次), 用 0ms/120ms/400ms 三次:
```python
def _settle():
    win.move(60, 40); win.raise_(); win.activateWindow(); _QA2.processEvents()
_QTM2.singleShot(0, _settle); _QTM2.singleShot(120, _settle); _QTM2.singleShot(400, _settle)
```

## 环境准备 (已做, 一次性)

```bash
~/.hermes/bin/uv venv /root/gui-venv --python /usr/bin/python3
~/.hermes/bin/uv pip install --python /root/gui-venv/bin/python PyQt5 numpy grpcio protobuf
# 冒烟: cd ~/lerobot-smolvla-lew/tools/gui && QT_QPA_PLATFORM=offscreen /root/gui-venv/bin/python -c "import importlib.util; spec=importlib.util.spec_from_file_location('studio','studio.py'); importlib.util.module_from_spec(spec)"
```

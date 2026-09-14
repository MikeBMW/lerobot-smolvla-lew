---
name: linux-chinese-input
description: "Use when 在 Linux/WSL/U盘Live系统装中文输入法 (ibus/fcitx5)."
version: 1.0.0
author: agent
tags: [linux, i18n, input-method, chinese, ibus, wsl]
platforms: [linux, wsl]
---

# Linux 中文输入法安装 (ibus-pinyin)

用户（老倪）中文交流，每台新 Linux 机器（WSL、U盘 Live 系统、服务器 GUI）的第一步就是装中文输入法。**优先沿用已配置的 IM 框架，改动最小**。

## 判断现状
```bash
env | grep -iE 'IM_MODULE|XMODIFIERS'     # 已有 ibus 配置 → 走 ibus 路线
which fcitx5 ibus fcitx 2>/dev/null       # 已装的框架
cat /etc/os-release | head -3
```
若 `XMODIFIERS=@im=ibus` / `QT_IM_MODULE=ibus` 已设 → **只补引擎，不要切 fcitx5**（切框架要改所有环境变量+重启，没必要）。

## 安装 + 启用（Ubuntu/Debian）
```bash
sudo apt-get install -y ibus-pinyin        # 提供 pinyin + libpinyin(智能拼音)
pgrep -a ibus-daemon                       # 看 daemon 是否在跑
ibus restart                               # 重启后新引擎才注册
sleep 2 && ibus list-engine | grep -i pinyin   # 确认 pinyin / libpinyin 已注册
ibus engine libpinyin                      # 设默认=智能拼音
ibus engine                                # 验证返回 libpinyin
```

## 持久化环境变量（写 ~/.bashrc）
```bash
grep -q 'GTK_IM_MODULE' ~/.bashrc || echo -e '\n# ibus 中文输入法\nexport GTK_IM_MODULE=ibus\nexport QT_IM_MODULE=ibus\nexport XMODIFIERS=@im=ibus' >> ~/.bashrc
```
注意：终端命令若被安全扫描标记为 "Dotfile overwrite" 属正常（追加 IM 变量到 .bashrc），可自动批准。

## 验证
- 新开的窗口（终端/GUI 程序）自动生效；老窗口要 `source ~/.bashrc` 或重开
- 切换中英文快捷键：`Ctrl+Space`

## 坑
- **VS Code snap 版永远打不出中文**：snap 运行时只带精简 GTK3 模块（无 im-ibus.so），且其 electron-launch 包装脚本无条件把 `GTK_IM_MODULE_FILE` 指向 snap 自己的 immodules 缓存（`~/snap/code/common/.cache/immodules/`，无 ibus 条目），还污染子进程环境：`GTK_PATH`/`LOCPATH`/`XDG_DATA_DIRS` 全指向 `/snap/code/...`。症状：怎么按切换键都没中文。**唯一正解：装 .deb 版**（`curl -sL -o code.deb "https://update.code.visualstudio.com/latest/linux-deb-x64/stable" && sudo apt install ./code.deb`）。对比：Chromium snap 用 gnome-platform 内容接口自带完整 GTK+im-ibus.so，所以浏览器能打中文而 VS Code snap 不能。
- **snap 终端会污染 GUI 程序**：从 VS Code snap 终端启动的任何 GUI 程序都继承被污染的 `GTK_IM_MODULE_FILE`/`GTK_PATH`/`LOCPATH` → GTK 找不到 ibus 模块（`No IM module matching GTK_IM_MODULE=ibus found`）。在 .bashrc 里 `unset GTK_IM_MODULE_FILE GTK_PATH LOCPATH GIO_MODULE_DIR` 修复。
- **Ubuntu 24.04 immodules.cache 的 ibus 条目带 locale 限制** `"ja:ko:zh:*"` — 但实测不影响 GTK3 模块加载（locale C 也能加载），是红鲱鱼；真正挡路的是上面 snap 污染。`LC_CTYPE=zh_CN.UTF-8` 可作为保险加上。
- **验证方法**：`env -i HOME=$HOME DISPLAY=:0 GTK_IM_MODULE=ibus XDG_DATA_DIRS=/usr/local/share:/usr/share PATH=/usr/bin:/bin python3 -c "import gi; gi.require_version('Gtk','3.0'); from gi.repository import Gtk; Gtk.init([]); w=Gtk.Window(); e=Gtk.Entry(); w.add(e); w.show_all(); import time; time.sleep(0.5); print('ok')"` 无 Gtk-WARNING 即 ibus 通路正常；再查 `/proc/<pid>/maps` 是否有 im-ibus.so。注意 zenity/gnome-text-editor 在 24.04 是 GTK4 应用，别拿它们测 GTK3 通路。
- **GNOME 桌面必查输入源注册**：daemon 在跑 + `ibus engine` 返回 libpinyin ≠ 能用。GNOME 自己管理输入源，必须把拼音注册进去，否则切换键无效（症状：怎么按都没中文）：
  ```bash
  gsettings get org.gnome.desktop.input-sources sources   # 若只有 [('xkb','us')] 就是没注册
  gsettings set org.gnome.desktop.input-sources sources "[('xkb', 'us'), ('ibus', 'libpinyin')]"
  ```
  设置后 GNOME 切换键是 Super+Space（Win+空格），Ctrl+Space (ibus) 也可用；顶栏出现「拼」即成功。
- `ibus restart` 后立刻 `ibus engine` 可能返回空 — daemon 还没就绪，等 1-2s 重试
- daemon 以 `--panel disable --xim` 运行是正常的（无桌面面板环境），XIM 兼容模式仍可用
- WSLg (DISPLAY=:0) 与 vcxsrv (DISPLAY=172.18.x.x:0) 两种显示方案下 ibus 均可用，无需区分

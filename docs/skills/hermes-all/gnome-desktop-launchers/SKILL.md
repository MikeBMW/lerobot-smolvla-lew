---
name: gnome-desktop-launchers
description: Use when GNOME桌面 .desktop 快捷方式有叉号/未信任/建桌面图标。DING缓存坑+修复序列。
---

# GNOME 桌面 .desktop 快捷方式维护 (Ubuntu 24.04 + DING)

## 触发场景
- 桌面 .desktop 快捷方式图标带叉号(未信任徽章), 或双击提示 "untrusted desktop file" / 无法启动
- 新建桌面快捷方式后图标不对/打不开
- 系统克隆/rsync 迁移后桌面快捷方式失效 (E盘迁移后 09-06 复现过)

## 叉号 = 什么
Ubuntu 24.04 (GNOME 46) 桌面图标由扩展 **Desktop Icons NG (ding@rastersoft.com)** 渲染。
.desktop 图标上的叉号 = DING 判定该启动器**未信任 (untrusted launcher)** = "不可运行"状态标记, 不是文件损坏、不是资源缺失。

## 信任判定三条件 (先查文件, 再动扩展)
1. 执行位: `ls -l ~/Desktop/*.desktop` → 须含 x (如 -rwxr-xr-x)
2. Exec / Icon 目标真实存在:
   - `ls -la <Exec路径>` — 脚本须存在且有 +x
   - Icon 可为主题图标名(utilities-terminal) 或绝对路径文件
3. trusted 元数据: `gio info ~/Desktop/X.desktop | grep trusted` → 须见 `xattr::metadata::trusted: true`

## 核心坑: DING 信任缓存不刷新
- DING 在文件创建/变更时缓存 `_trusted=false`; 事后 `gio set metadata::trusted true` **只写 xattr, 不触发 inotify**, 扩展不会重读 → 叉号不退 (08-23 首犯, 09-06 克隆后复发)
- 克隆/rsync 迁移后 xattr 丢失或缓存陈旧都会让叉号重现

## 修复序列 (08-23 与 09-06 两次实测有效)
```
touch ~/Desktop/X.desktop                       # 触发 IN_MODIFY 让扩展重载
gio set ~/Desktop/X.desktop metadata::trusted true   # 幂等重写
gnome-extensions disable ding@rastersoft.com && sleep 1 && gnome-extensions enable ding@rastersoft.com
```
只重启 DING 扩展即可; **勿重启 gnome-shell**(整屏闪、丢用户 GUI 状态)。

## 环境专属知识 (老倪这台 E盘 Ubuntu)
- LiveUSB 迁移残留: `ubuntu-desktop-bootstrap*.desktop` = "Install Ubuntu" 安装向导入口。它在桌面上带叉号属正常(本来就不是日常应用), 误点会启动安装向导; 处理 = 改名 `.bak` 隐藏保留(老倪铁律: 删东西先改名, 不真删)
- 标准桌面配套: .desktop 的 Exec 指向仓库内启动脚本(如 `tools/gui/launch_studio.sh`), 脚本硬编码 venv python 并防重复启动 — 相关 GUI 工程细节见 zmax-console 技能
- Desktop 目录健康检查辅助: 确认 Exec 里 Terminal=true/false 语义正确(不影响信任判定, 只影响是否弹终端)

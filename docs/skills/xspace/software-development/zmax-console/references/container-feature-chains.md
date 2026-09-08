# 容器环境功能链路自适应 (2026-08-18 实测)

## 背景

新家容器 = 纯 Docker Desktop (192.168.65.x): **无 /mnt/c、无 explorer.exe、无 wsl.exe、
无 WSL interop**。凡 GUI 功能依赖 Windows 通道 (explorer 打开 / 盘符路径 / cmd.exe) 的,
在容器内**必挂**, 且用户表现为"功能点了没反应/打不开"。

## 实例: 右键「打开源代码」打不开 (open_node_source)

- 症状: 状态空间画布右键任意节点 →「打开源代码」无反应。日志 `⚠️ 打开源码失败`。
- 根因: 老链路 (2026-08-12 WSL 老家写的) = `shutil.copy2(path, "/mnt/c/zmax_src_view/...")`
  + `explorer.exe` 打开。容器里 /mnt/c 不存在 → copy2 抛 FileNotFoundError → except 吞掉。
- 修复 (已提交): open_node_source 环境自适应:
  ```python
  if os.path.isdir("/mnt/c") and shutil.which("explorer.exe"):
      # WSL 老家: 老链路 (复制 + explorer.exe)
  else:
      # 容器: SourceViewDialog 弹窗 (node_logic_dialog.py)
  ```
  SourceViewDialog = 文件绝对路径(金色可选中) + 📋复制路径按钮 + 只读源码带行号
  (等宽字体, 可选中复制)。符合老倪 VSCode 偏好 (绝对路径+行号+复制按钮)。

## 铁律 (新功能设计时)

**要走 Windows 侧 (explorer / 浏览器 / 盘符路径 / cmd.exe) 的功能, 一律先探测
`os.path.isdir("/mnt/c") and shutil.which("explorer.exe")`**; 容器环境必须给容器内回落方案
(弹窗/内嵌查看/复制路径), 别假设 WSL 通道存在。launch-guide.md 的"新家"一节有环境全貌。

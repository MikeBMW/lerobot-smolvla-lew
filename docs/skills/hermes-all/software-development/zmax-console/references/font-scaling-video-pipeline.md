# 字体缩放 & 状态空间视频生成管线 (2026-08-22)

## 字体缩放 — DPI 变了，pt 值渲染物理尺寸减半

### 根因
老倪反复说"画布字体还是太小"，根因是**显示环境 DPI 变了**：
- 旧家 WSLg = **192 DPI**，新家 U 盘 live (GNOME X11) = **96 DPI**。
- QFont 用 **point (pt)** 单位，pt 是物理单位（1pt=1/72 英寸）→ 96 DPI 下 1pt≈1.33px，
  192 DPI 下 1pt≈2.67px。**同样的 pt 值在 96 DPI 下渲染像素只有 192 DPI 的一半**。
- 所以历史上按 192 DPI "收敛过" 的 9pt 节点标题，在 96 DPI 屏上物理看起来小了一倍。

### 第一步永远是查 DPI，别盲目加 pt
```bash
DISPLAY=:0 xdpyinfo | grep -iE 'resolution|dimensions'
```
`resolution: 96x96` = 低 DPI 大屏 → 字号要往上加；`192x192` = 高 DPI → 原值偏大。

### 字号层级 (2026-08-22 定稿, 96 DPI)
放大字体时节点高度 `DH` 必须同步加大（50→60），否则大字号标题溢出方块。

| 位置 | 字号 |
|---|---|
| CICD 环节标题 (CICDStageItem) | 15pt Bold |
| 普通节点标题 (递减序列 for _fs) | 14 / 13 / 12 |
| 状态徽章 / 悬停ID | 13pt Bold |
| 辅助小字 (ID/类型标签) | 11pt |
| 参数值 (Consolas) | 12pt |
| 左侧库分组标题/按钮 | 10pt (QSS) |
| 右侧 model_tree | 全部 font-size +4px 累计 |

### ⚠️ 批量改字号的坑：顺序正则替换会连锁误伤
用 `re.subn` 做**顺序**替换时，前一条的产物会被后一条再次匹配：
```python
# 错误：先 11bold→13，再 13bold→15 → 刚变成13的4处又被拉到15，层级被抹平
rep(r'QFont\("Arial", 11, QFont\.Bold\)', '...13...')
rep(r'QFont\("Arial", 13, QFont\.Bold\)', '...15...')  # 把上面4处也吞了
```
结果标题和徽章全是 15，层级丢失。

**正确做法**：按行号精确改，或单次映射（一次性 dict/回调，避免链式）；改完必须 grep 验证最终层级：
```bash
grep -oE 'QFont\("[^"]*", [0-9]+[^)]*\)' simulink_module.py | sort | uniq -c
```
`^DH = 50` 这种正则锚点注意：`re.subn` 默认不开多行，`^` 只匹配字符串开头 → 用 `re.M` 或直接按行号改。

## 状态空间操作视频生成管线 (gen_state_space_video.py)

### 触发链
状态空间仿真完成 → `_start_video_export` 后台线程 → **子进程**跑 `gen_state_space_video.py`。
关键：子进程用 `sys.executable`，即 **GUI 自己的解释器 = gui-venv311**，不是系统 python3。

### 依赖三件套 (缺一即报错)
1. **Pillow** — 必须装进 gui-venv311：
   `~/.hermes/bin/uv pip install --python <repo>/gui-venv311/bin/python Pillow`
   系统 python3 有 PIL 不算数（子进程不用它）。报错 `No module named 'PIL'`。
2. **中文字体** — 脚本原硬编码 `wqy-microhei.ttc`，但 U 盘 live 上没有（只有 NotoSansCJK）。
   已改为**候选列表自动探测**（`next(f for f in CANDIDATES if os.path.isfile(f))`），
   兜底 `NotoSansCJK-Regular.ttc`。`ImageFont.load_default()` 不支持中文会渲染成方块。
3. **ffmpeg** — `sudo apt-get install -y ffmpeg`，合成 mp4 必需，报错在最后一步才暴露。

### 上传链路 (sshpass + scp → ECS)
`sshpass -p Nix19789 scp ... root@39.102.211.79:/www/wwwroot/datadrive.world/`
- **sshpass 需 apt 安装**（本机不预装），否则报 `No such file or directory: 'sshpass'`。
- 上传后 `chmod 644`，公网 `https://datadrive.world/state_space_sim.mp4` 可访问。
- 验证：`curl -sS -o /dev/null -w '%{http_code} %{size_download}' <url>`。
- ⚠️ ECS 密码 Nix19789 **有效**（08-22 实测 AUTH_OK）；08-13 记录"失效"是网络被墙的误判，非密码错。

### 杀 studio.py 实例 (勿用 pkill -f 自杀)
`pkill -9 -f "gui-venv311/bin/python studio.py"` 会匹配到**命令自身** → 连 shell 一起 SIGKILL。
正确：
```bash
ps aux | grep "gui-venv311/bin/python studio" | grep -v grep | awk '{print $2}' | while read p; do kill -9 "$p"; done
```

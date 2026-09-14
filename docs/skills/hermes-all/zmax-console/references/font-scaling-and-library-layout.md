# 字体缩放 (DPI) + 模块库布局 + 视频生成依赖 — 2026-08-22 实测

## 根因: 96 DPI vs 192 DPI — 同样 pt 值物理像素减半

- 之前 WSLg 环境是 192 DPI, 画布节点字号 (QFont pt) 是按 192 DPI "收敛过"的值。
- 当前 U盘 live 环境 96 DPI (`xdpyinfo | grep resolution` → 96x96)。
- 同样 pt 值在 96 DPI 下物理像素只有 192 DPI 的一半 → 用户反复报"字体太小"。
- 教训: 调字号前先 `xdpyinfo` 确认 DPI, 别照搬上一台机器的字号值。

## 画布节点字号层级 (simulink_module.py, 96 DPI 最终值)

- CICD 环节标题: 15pt bold (`CICDStageItem`)
- 节点标题递减: `for _fs in (14, 13, 12)` — 超宽自动降号 + 拆两行, 不截断
- 状态徽章 / 悬停 ID / `_paint_internal` 标题: 13pt bold
- 辅助小字 (ID / 类型标签): 11pt
- 参数 Consolas: 12pt
- 节点高度 `DH = 60` (原 50 — 字号放大后标题会溢出 50px 方块, 必须同步加高)

## 左侧模块库 (LibraryPanel) + 右侧数据字典 (model_tree.py)

- LibraryPanel `setFixedWidth(360)` (原 280 — 放大字体后模块名放不下)
- LibraryPanel QSS 字号用 **pt**: 分组标题/模块按钮 10pt, 标题 11.5pt, 提示 11pt
- model_tree.py 用 QSS `font-size:Npx` — 统一 +Npx 缩放 (40 处)
- ⚠️ 三处字体单位不同: 画布节点=pt, 左侧库=pt, 右侧树=px。放大必须三处一起改, 漏一处就"大小不统一"。

## 🐛 批量替换字号的正则链陷阱 (本次踩坑)

用多个 `re.subn` 顺序替换字号, 中间值会被后续规则再匹配 → 过度放大、层次丢失:

```python
# ❌ 错误: 11bold→13 先执行, 把 4 处普通节点标题也变 13bold;
#   紧接着 13bold→15 把它们连同原本就 13 的 CICD 标题一起拉到 15 → 徽章和标题全 15, 层次丢了
re.subn(r'QFont\("Arial", 11, QFont\.Bold\)', '...13...', s)
re.subn(r'QFont\("Arial", 13, QFont\.Bold\)', '...15...', s)
```

- ✅ 正确做法: (a) 单次正则带回调按原值一次映射; 或 (b) 先 `grep -n` 出所有目标行号, **按行号精确改** (assert old in line), 每行只改一次。
- 改完必须 `grep -nE 'QFont\("Arial", [0-9]+, QFont\.Bold\)'` 复查层次, 别只看"替换了几处"。目标是标题>徽章>小字 的清晰层级。

## 模块库折叠/展开重构 (去掉"啥也没有"的空扩展条)

- 旧实现: library 右侧一个独立 16px `_lib_expand_bar` QPushButton("▶"), `setVisible(False)` 隐藏但仍在 QSplitter 里占一个空白分割位置 → 拖动时露出"啥也没有"的空白, 用户要求去掉。
- 新实现: 删掉独立窄条。LibraryPanel 自折叠 — `set_collapsed(True)` 收窄到 20px 只显示 `_btn_expand`(▶), `False` 恢复 360px 完整面板。信号: `collapse_requested` + `expand_requested` (都是 pyqtSignal)。
- split 只剩 [library | mdi] 两个 widget, `setStretchFactor(0,0)/(1,1)`。
- 要点: 折叠/展开条别再做成独立 QSplitter 子项 — 做成 panel 内部自收窄, 否则隐藏的条仍留空白分割位置。

## 状态空间视频生成依赖链 (gen_state_space_video.py)

- 脚本用 `sys.executable` (=gui-venv311 的 Py3.11) 跑, 依赖: **Pillow + numpy + ffmpeg + 中文字体 + sshpass(上传)**。
- Pillow 缺失会直接 `ModuleNotFoundError: No module named 'PIL'` (GUI 里显示"视频生成失败")。
- 装 Pillow: `~/.hermes/bin/uv pip install --python <gui-venv311>/bin/python Pillow`
- ffmpeg: `sudo apt-get install -y ffmpeg`; sshpass: `sudo apt-get install -y sshpass`
- 🐛 中文字体路径 `_FONT` 原硬编码 wqy-microhei.ttc (本机无此字体) → 已改成候选列表 `next(f for f in _FONT_CANDIDATES if os.path.isfile(f), _FONT_CANDIDATES[0])`, 落到 NotoSansCJK-Regular.ttc。`ImageFont.load_default()` 不支持中文, 会渲染成方块 — 别依赖它当回退。
- 上传 ECS: `sshpass -p Nix19789 scp ... root@39.102.211.79:/www/wwwroot/datadrive.world/` + `chmod 644`。密码 Nix19789 实测有效 (08-22)。

## 修完验证

- `python -c "import ast; ast.parse(open('studio.py').read())"` 语法 OK
- 端到端: `gen_state_space_video.py /tmp/test.mp4` → ffprobe 看 codec_name=h264 / 帧数 / duration
- 上传后 `curl -sS -o /dev/null -w "%{http_code}" https://datadrive.world/state_space_sim.mp4` = 200

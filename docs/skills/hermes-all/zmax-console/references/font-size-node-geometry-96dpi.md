# 字体/节点尺寸 — 96 DPI 环境 + JSON 固化尺寸坑 (2026-08-22)

本机 = U盘 live Ubuntu GNOME X11, **96 DPI** (xdpyinfo: resolution 96x96)。旧 WSLg 是 192 DPI。
pt 字号渲染像素 = pt × DPI/72, 所以 **同样 pt 值在 96 DPI 下物理像素只有 192 DPI 的一半** → 历史上按 192 DPI 调好的字号 (9pt 等) 在本机显得极小。

## 最终协调比例 (老倪定稿, 别乱动)
- 普通节点: **240×84** (DH=84, 默认宽 240)
- CICD 环节项: 240×92
- 节点标题: 12pt 递减 (12/11/10) — 超宽自动降号+拆两行
- CICD 环节标题: 13pt; 状态徽章/悬停ID: 11pt; 辅助小字: 10pt; 参数 Consolas: 10pt
- 布局间距: 列距 300, 行距 260
- 关键教训: 字体放大后**框必须同步放大**到能容纳, 否则"字大框小"老倪直接炸。

## 🐛 头号坑: JSON flow 文件固化了旧节点尺寸, setdefault 压不住
`flows/model_zoo.json` 等文件里普通节点显式写了 `"w": 150`(202个)/`"w": 180`(244个)/`"w": 170`等旧值。
加载时 `node.setdefault("w", 240)` **只在 key 不存在时才生效** → JSON 旧值把新默认值压制,
结果: 字体改大了(生效) 但框没变大(被 JSON 旧值覆盖) → "字大框小"。

**修法**: `load_flow` 和 `load_flow_file` 两条加载路径, 对非 row_bg 节点**强制最小尺寸**:
```python
if node.get("type") != "row_bg":
    node["w"] = max(node.get("w") or 0, 240)
    node["h"] = max(node.get("h") or 0, DH)
else:
    node.setdefault("w", 240); node.setdefault("h", DH)
```
row_bg 背景行保留自定义尺寸 (w=1070/3000/2660 等整行跨度) 不能动。
⚠️ 通用教训: 改默认尺寸时, 一定要 `grep flows/*.json` 看有没有固化旧值, 否则改了等于没改。

## 🐛 顺序字符串替换会级联误伤 (批量改字号必看)
连续 `str.replace` 改字号时, 前一步产物会被后一步规则再匹配:
`QFont("Arial",11,Bold)→13` 先跑, 然后 `→15` 的规则把刚生成的 13 也一起拉到 15 → 4 处普通节点标题被误伤成 CICD 标题同号。
**修法**: 用正则**单次回调映射** (每个 QFont 只处理一次), 不要顺序链式 replace:
```python
def _map(m):
    fam, n, bold = m.group(1), int(m.group(2)), m.group(3) or ""
    new = {15:13, 13:11, 12:10, 11:10}.get(n, n) if (fam=="Arial" and bold) else n
    return f'QFont("{fam}", {new}{bold})'
re.subn(r'QFont\("(Arial|Consolas)", (\d+)(, QFont\.Bold)?\)', _map, s)
```
或按行号精确修 (行号-1 索引)。改完必须 `grep` 最终字号分布确认层次正确。

## 左侧模块库折叠 (LibraryPanel)
- 原设计: 独立 16px `_lib_expand_bar` QPushButton 插在 QSplitter 里, `setVisible(False)` 后**仍占一个可拖动的空白分割槽** → 用户拖动时露出"啥也没有"的空白区。
- 修法: 删掉独立展开条, LibraryPanel 自折叠 `set_collapsed(bool)` — 收起时隐藏内容+`setFixedWidth(20)`只留 ▶ 按钮, 展开恢复 360。split 只留 [library | mdi] 两 widget。
- 面板宽 360 (容纳放大后的模块名)。

## 视频生成依赖链 (gen_state_space_video.py)
- 跑在 gui-venv311 (sys.executable), 依赖 **Pillow + numpy** — Pillow 一度缺失 (报 `ModuleNotFoundError: No module named 'PIL'`)。
- 装法: `~/.hermes/bin/uv pip install --python <venv>/bin/python Pillow`
- 中文字体: 硬编码 `wqy-microhei.ttc` 在本机不存在 → 改候选列表自动探测 (落到 NotoSansCJK-Regular.ttc)。
- ffmpeg 合成 mp4, 需 apt 安装。

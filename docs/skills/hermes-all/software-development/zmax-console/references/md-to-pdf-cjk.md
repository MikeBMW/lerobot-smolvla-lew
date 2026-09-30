# 帮助文档 → PDF 导出 (md_to_pdf, 2026-08-12)

功能: studio.py 帮助文档菜单「📄 导出文档为 PDF…」→ 选 md → docs/pdf/ → 复制 C 盘打开。
工具: tools/gui/docs_pdf.py, 命令行: `.venv/bin/python docs_pdf.py <in.md> <out.pdf>` (exit 0/1)。

## 踩过的坑(全链路)

1. **Noto CJK 是 CFF/PostScript 轮廓 → reportlab TTFont 报 "postscript outlines are not supported"**
   系统 `/usr/share/fonts/opentype/noto/NotoSansCJK-*.ttc` 虽存在但 reportlab 不支持。
   修复: `sudo apt-get install -y fonts-wqy-microhei` → `/usr/share/fonts/truetype/wqy/wqy-microhei.ttc`
   (TrueType 轮廓, TTFont 可注册, subfontIndex=0)。

2. **fitz.Story 在此环境失效**: PyMuPDF 1.28 `fitz.Story(...).place(dev)` 渲染 0KB(一页都不填);
   `insert_htmlbox` 正常但返回的"使用高度"≈矩形高度(不可用于分页推进)。
   → 放弃 fitz, 用 reportlab SimpleDocTemplate(自动分页, 可靠)。

3. **emoji 在 WQY 无字形 → 渲染空字符/方块**: `_esc()` 里剥离 `[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200d]`。
   验证提取文本时断言 `chr(0) not in txt[:200]` 可查。

4. **GUI 用系统 python3(无 reportlab/fitz)**: studio.py 的 `_export_doc_pdf` 不能直接 import docs_pdf →
   用 `.venv/bin/python docs_pdf.py <md> <out>` 子进程跑转换(`subprocess.run(timeout=120)`),
   成功条件 `returncode==0 and os.path.exists(out)`。

5. **导出后 Windows 打开**: 复制到 `/mnt/c/Users/Public/ZMAX_docs` + `cmd.exe /c start "" <反斜杠路径>`。

## md 解析(轻量, docs_pdf.py 已实现)
- `#/##/###` 标题 · `-` 列表(bulletText) · ` ``` ` 代码块(Preformatted) · 表格(Table, 连续 `|` 行)
- `---` 分隔线 · 行内 `**bold**`/`` `code` ``/`[text](url)` 降级纯文本(Paragraph 不支持富文本)
- 中文字体常量 `_WQY` + `_ensure_font()`(TTFont subfontIndex=0)

## 验证
`python3 -m py_compile studio.py` + venv py_compile docs_pdf.py; GUI 链路实测 = venv 子进程转 3-4 篇
真实 docs/*.md, 断言: `%PDF-` 头、>3KB、venv fitz 提取文本含中文关键词、页数 2-8。

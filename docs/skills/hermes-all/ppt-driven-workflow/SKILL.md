---
name: ppt-driven-workflow
description: PPT to console via markers. Template match, arch, sync.
trigger: User wants to drive console actions from PowerPoint, generate arch slides, or sync PPT content with console UI.
---

# PPT-Driven Workflow Skill

Use PowerPoint as a bidirectional control interface: write markers in PPT to trigger console actions, and generate PPT slides from console content.

## Core Concepts

### The "V 静" Marker Convention

The actual marker used in production is **`V 静`** (not `▶ 静`). Place in top-right corner:

| Marker | Meaning |
|--------|---------|
| `V 静` | Draw/update Z-MAX system architecture on this slide |
| `V 指令` | Parse this slide as an executable instruction |
| `📥` | Sync documents from GitHub |
| `📤` | Push local changes to GitHub |

The marker should have a light orange background (`#FFF3E0`) and orange border (`#F7A90B`) for visibility on both white and dark backgrounds.

### Template Colors (White PPT Template)

**CRITICAL: Match the target PPT's template, NOT the console's dark theme.** The agent's default dark bg (#06080d) and teal accents (#00d4aa) will NOT match a typical white/light template. Always inspect the first 3 slides:

```python
try: bg = str(slide.background.fill.fore_color.rgb)
except: bg = 'inherited from layout'
for sh in slide.shapes:
    if sh.has_text_frame:
        for p in sh.text_frame.paragraphs:
            for r in p.runs:
                try: print(f'color=#{r.font.color.rgb} size={r.font.size}')
                except: pass
```

Most Chinese business PPT templates:
- **Background**: `#FFFFFF` (white) — inherited from layout
- **Title text**: `#002060` (dark blue), 22-24pt bold, Microsoft YaHei
- **Body text**: `#000000` (black), 9-12pt
- **Accent**: `#0070C0` (blue), `#F7A90B` (orange)
- **Layout**: "横线" on Master 1

Always use `prs.slides.add_slide(prs.slide_masters[1].slide_layouts[4])` for the 横线 layout, NOT slide_layouts[6] (blank).

### Critical Rule: Clone, Don't Build Shapes

The single most important lesson from repeated failures:

**NEVER build PPT shapes from scratch** (rounded rects, text boxes, connectors, fills) using python-pptx for a user's existing template. The result will NEVER match — colors are slightly off, border radii differ, spacing doesn't align. The user will reject it every time.

**ALWAYS:**
1. Add a slide using the SAME layout as existing content slides
2. Only add text-based content on top — text boxes with matching font/color
3. For complex diagrams (architecture layers): let the user draw the structure manually, then read and replicate their EXACT layout
4. For shape-rich slides: deep-copy an existing content slide XML and only change text

```python
# WRONG — building shapes from scratch:
shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, ...)  
# NEVER matches template fill/line/radius exactly

# BETTER — add slide with correct layout, only add text:
sd = prs.slides.add_slide(prs.slide_masters[1].slide_layouts[4])  # 横线
txBox = sd.shapes.add_textbox(l,t,w,h)  # just text
p = txBox.text_frame.paragraphs[0]
p.text = "content"; p.font.color.rgb = RGBColor(0x00,0x20,0x60)  # match template
```

If the user manually drew their layout and wants you to replicate it:
1. Read every shape's position, size, fill, border, and text
2. Clear ALL shapes from the slide
3. Rebuild with EXACTLY the same parameters (do not adjust or improve)
4. Only change text content if explicitly asked

5. **Arrowheads on connectors**:
   ```python
   import lxml.etree as etree
   c = slide.shapes.add_connector(1, x1, y1, x2, y2)
   ln = c._element.find('{http://schemas.openxmlformats.org/drawingml/2006/main}ln')
   if ln is None:
       ln = etree.SubElement(c._element, '{http://schemas.openxmlformats.org/drawingml/2006/main}ln')
   te = etree.SubElement(ln, '{http://schemas.openxmlformats.org/drawingml/2006/main}tailEnd')
   te.set('type', 'triangle')
   ```

6. **Removing slides** (python-pptx limitation):
   ```python
   sldIdLst = prs._element.find('{http://schemas.openxmlformats.org/presentationml/2006/main}sldIdLst')
   last = sldIdLst[-1]
   rId = last.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
   sldIdLst.remove(last)
   prs.part.rels.pop(rId)
   ```

### Sync & Distribution

- Local PPT files on Windows: `D:\静界\`
- WSL path: `/mnt/d/静界/`
- GitHub backup: `docs/` in the repo
- Console sync: `帮助文档 → 📥 同步文档`

### Pitfalls

- **PowerPoint locks files**: If the user has the PPT open, `cp` to `D:\静界\` will fail with "Permission denied". Tell user to close PPT first.
- **White fill on white bg**: `#FFFFFF` fill on white background is invisible. Use `#FFF3E0` for marker backgrounds.
- **PyYAML parses `on:` as boolean True**: In GitHub Actions YAML, use `"on":` (quoted) to avoid PyYAML treating it as `True`.
- **Don't invent content**: If the user says "don't change the content", keep all text EXACTLY as-is. Only modify visual presentation.
- **Template colors matter**: Always check existing slides for the correct color palette before generating new content.

### Verification

After editing a PPT, verify:
```python
from pptx import Presentation
prs = Presentation(path)
s = list(prs.slides)[-1]
print(f'Layout: {s.slide_layout.name}')
print(f'Slides: {len(list(prs.slides))}')
for sh in s.shapes:
    if sh.has_text_frame and sh.text_frame.text.strip():
        print(f'  {sh.text_frame.text[:40]}')
```

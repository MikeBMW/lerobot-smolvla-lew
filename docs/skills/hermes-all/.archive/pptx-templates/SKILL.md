---
name: pptx-templates
description: "Edit PPTX templates with python-pptx preserving layout."
version: 1.0.0
author: xspace
license: MIT
metadata:
  hermes:
    tags: [PowerPoint, PPTX, Templates, python-pptx, Presentations]
    category: productivity
    related_skills: [powerpoint]
---

# PPTX Template Editing (python-pptx)

Edit existing `.pptx` template decks while preserving their native look — custom slide masters, layouts, backgrounds, and accent colors. Use this when the existing `powerpoint` skill's pptxgenjs/Node.js approach would lose the template's styling.

## When to Use

Use this skill when:
- You have an **existing .pptx template deck** whose layout, background, colors, and fonts must be preserved
- The deck uses **custom slide masters or layouts** (e.g., named layouts like "横线", "共形")
- You need to **add slides that match the template's visual style** — same background, same title fonts/colors, same accent palette
- You need to **programmatically add connectors with arrowheads** (python-pptx connectors don't expose arrowheads through the high-level API)
- You want a **marker-based communication system** between PPT slides and a control application (e.g., `"V 静"` marker triggers console actions)

## Prerequisites

```bash
pip install python-pptx lxml
```

## Quick Reference

### 1. Find custom slide layouts

List all layouts across all masters (including custom ones):

```python
from pptx import Presentation
prs = Presentation("deck.pptx")
for mi, master in enumerate(prs.slide_masters):
    for li, layout in enumerate(master.slide_layouts):
        print(f"Master {mi} Layout {li}: \"{layout.name}\"")
```

Custom layouts often live on a separate master (Master 1+) while the built-in layouts (TITLE, OBJECT, BLANK) are on Master 0.

### 2. Add a slide using a custom layout

```python
layout = prs.slide_masters[m].slide_layouts[l]
slide = prs.slides.add_slide(layout)
# slide now inherits the template background, title placeholders, etc.
```

### 3. Extract the deck's actual colors

Never assume dark/light theme — read the first few slides:

```python
for slide in list(prs.slides)[:3]:
    for sh in slide.shapes:
        if sh.has_text_frame:
            for p in sh.text_frame.paragraphs:
                for r in p.runs:
                    try:
                        print(f"text color: #{r.font.color.rgb}")
                        print(f"font size: {r.font.size}")
                        print(f"bold: {r.font.bold}")
                    except: pass
```

### 4. Add connectors with arrowheads

python-pptx `add_connector` does not expose arrowheads through the high-level API. Set them via XML:

```python
import lxml.etree as etree

def add_arrow(slide, x1, y1, x2, y2, color, width=Pt(2)):
    c = slide.shapes.add_connector(1, x1, y1, x2, y2)
    c.line.color.rgb = color
    c.line.width = width
    ln = c._element.find('{http://schemas.openxmlformats.org/drawingml/2006/main}ln')
    if ln is None:
        ln = etree.SubElement(c._element, '{http://schemas.openxmlformats.org/drawingml/2006/main}ln')
    tail = etree.SubElement(ln, '{http://schemas.openxmlformats.org/drawingml/2006/main}tailEnd')
    tail.set('type', 'triangle'); tail.set('w', 'med'); tail.set('len', 'med')
    return c
```

### 5. Marker system for PPT to app communication

Place a distinctive marker shape at the top-right of a slide (e.g., `"V 静"`) to signal the console/application that this slide needs processing. The marker must be **visible on the template's background** — use a light warm fill if the template is white:

```python
sq = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
    Emu(10400000), Emu(200000), Emu(1600000), Emu(500000),
    RGBColor(0xFF, 0xF3, 0xE0), outline_color)
sq.line.width = Pt(2)
tb = slide.shapes.add_textbox(Emu(10400000), Emu(200000), Emu(1600000), Emu(500000))
p = tb.text_frame.paragraphs[0]; p.text = "V 静"
p.font.size = Pt(16); p.font.color.rgb = outline_color; p.font.bold = True
```

### 6. Delete a slide (python-pptx limitation)

python-pptx has no `delete_slide()`. Remove via XML manipulation:

```python
pres_elem = prs._element
sldIdLst = pres_elem.find('{http://schemas.openxmlformats.org/presentationml/2006/main}sldIdLst')
last_elem = sldIdLst[-1]
rId = last_elem.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
sldIdLst.remove(last_elem)
prs.part.rels.pop(rId)
prs.save("out.pptx")
prs2 = Presentation("out.pptx")  # re-open for clean state
```

### 7. Clear shapes from a slide

```python
for sh in list(slide.shapes):
    sh._element.getparent().remove(sh._element)
```

## Pitfalls

- **python-pptx cannot read SVG/EMF images** — `add_picture` raises `UnidentifiedImageError`. Duplicate a slide that already contains the image instead.
- **Setting `text_frame.text = "..."` collapses formatting** — it replaces all runs with a single unstyled run. Assign `run.text` on individual runs instead.
- **Slide background is often inherited from the layout**, not set per-slide. Check `slide.slide_layout.background` for the actual background.
- **Connector arrowheads are not in the high-level API** — always use the XML approach above.
- **Deep-copying slide XML** to clone a slide requires careful relationship management. Prefer `add_slide(layout)` with the correct layout.
- **Tuple colors, not hex strings**: python-pptx uses `RGBColor(r, g, b)` tuples. Never pass hex strings like `"FF0000"` to shape fills.
- **White fill on white background is invisible** — when adding a marker on a light template, always give it a contrasting background fill (e.g., `#FFF3E0` light orange).
- **Template background may be inherited, not per-slide** — `slide.background.fill.fore_color` may error or return a default. The actual background comes from the **slide layout** (`slide.slide_layout`). Always check both `slide.background` and `slide.slide_layout.background`.
- **Never assume dark/light without checking** — guessing "dark" on a white template makes every shape look wrong. Inspect BOTH the slide background AND actual text fills from paragraph runs before choosing colors. Multiple mismatch rounds frustrate the user; one inspection prevents many iterations.
- **`slide.background.fill.type` may be `None`** — when `bg.type is None`, the slide inherits from its layout. Check `slide.slide_layout.background.fill` for the actual theme.

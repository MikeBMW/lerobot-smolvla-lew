# python-pptx Build Helpers for PPT Slide Manipulation

Helper functions used to build Z-MAX architecture slides matching the user's template.

## Core Helpers

```python
def rect(slide, left, top, width, height, fill=None, border=None):
    """Add a rounded rectangle"""
    s = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
    s.fill.solid(); s.fill.fore_color.rgb = fill or default_bg
    if border: s.line.color.rgb = border; s.line.width = Pt(1)
    else: s.line.fill.background()
    s.adjustments[0] = 0.05
    return s

def txt(slide, left, top, width, height, text, size=Pt(11), color=black, bold=False, align=PP_ALIGN.CENTER):
    """Add a text box"""
    tb = slide.shapes.add_textbox(left, top, width, height)
    tf = tb.text_frame; tf.word_wrap = True
    p = tf.paragraphs[0]; p.text = text
    p.font.size = size; p.font.color.rgb = color
    p.font.bold = bold; p.alignment = align
    p.font.name = "Microsoft YaHei"
    return tb

def arrow_connector(slide, x1, y1, x2, y2, color, width=Pt(2)):
    """Add a connector line with arrowhead"""
    c = slide.shapes.add_connector(1, x1, y1, x2, y2)
    c.line.color.rgb = color; c.line.width = width
    import lxml.etree as etree
    ln = c._element.find('{http://schemas.openxmlformats.org/drawingml/2006/main}ln')
    if ln is None:
        ln = etree.SubElement(c._element, '{http://schemas.openxmlformats.org/drawingml/2006/main}ln')
    te = etree.SubElement(ln, '{http://schemas.openxmlformats.org/drawingml/2006/main}tailEnd')
    te.set('type', 'triangle'); te.set('w', 'med'); te.set('len', 'med')
    return c
```

## Remove Last Slide

```python
# python-pptx has no built-in delete_slide. Use XML manipulation:
pres_elem = prs._element
sldIdLst = pres_elem.find('{http://schemas.openxmlformats.org/presentationml/2006/main}sldIdLst')
if sldIdLst is not None and len(sldIdLst) > 0:
    last = sldIdLst[-1]
    rId = last.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
    sldIdLst.remove(last)
    prs.part.rels.pop(rId)
```

## Find Slide Layout by Name

```python
for mi, master in enumerate(prs.slide_masters):
    for li, layout in enumerate(master.slide_layouts):
        print(f'Master {mi}, Layout {li}: "{layout.name}"')
```

## Z-MAX Slide 24 Layout (exact positions)

```
Title:      (333138, 118973) 10515600x363875
Frame:      (2496000, 909956) 7200000x5398395
SYS 2 bar:  (3216000, 1269000) 5760000x1080000  (purple #7B2DC0)
SYS 1 bg:   (3216000, 2708043) 5760000x1800958  (blue #4472C4)
  SYS 11:   (3576000, 3068995) 2520000x1080000  (light blue #58A6FF)
  SYS 12:   (6096000, 3068995) 2520000x1080000  (blue #0070C0)
SYS 0 bar:  (3216000, 4868044) 5760000x1080000  (red #C00000)
V 静 marker:(10848737, 91424)  804693x363875     (orange #F7A90B)
```

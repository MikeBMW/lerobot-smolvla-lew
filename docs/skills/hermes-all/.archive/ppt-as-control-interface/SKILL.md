---
name: ppt-as-control-interface
description: Drive a desktop console via PPT slides with markers.
---

# PPT-as-Control-Interface

Use PowerPoint slides as the command source for a desktop console app. Each slide = one instruction. Markers in the slide signal intent.

## Marker System
Place a marker in the PPT slide's top-right:

| Marker | Meaning |
|--------|---------|
| `V 静` | Draw/update Z-MAX system architecture |
| `V 指令` | Parse this slide as an executable instruction |

Markers: orange border, `#FFF3E0` fill, bold, top-right.

## Template Matching (CRITICAL)
**Always match the existing PPT template.** Never invent colors/shapes.

1. Find the correct layout: `prs.slide_masters[i].slide_layouts[j]`
2. Clone an existing slide to preserve styling
3. Clear shapes, keep layout
4. Use the template's own colors

## Style Rules
- Do NOT change or invent content
- Layout first — replicate exact positions/sizes
- Push to GitHub; D:\静界\ is the user's workspace

## Console Integration
ArchitectureModule uses QFrame with styled backgrounds (not ASCII art):
- Three rows, not three columns
- V 静 marker at top-right
- Arrow labels between layers

## python-pptx Notes
- Connector arrows: `c._element` not `c.line._element`
- Remove shapes: `sh._element.getparent().remove(sh._element)`
- Slide dims: 12192000 x 6858000 EMU

## Pitfalls
- ❌ White template = white background, never dark
- ❌ Do not overwrite user's manual edits
- ❌ D:\静界\ copy fails when PPT has file open
- ⚠ PyYAML parses `on:` as True — quote it `"on":`

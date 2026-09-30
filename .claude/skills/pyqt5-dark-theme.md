---
name: pyqt5-dark-theme
description: Common PyQt5 styling pitfalls in dark themes, especially button color bleed and transparent border issues
tags: [pyqt5, pyqt, qt, dark-theme, styling, css, gui, buttons]
version: 1
---

# PyQt5 Dark Theme Styling Pitfalls

## Critical Lesson: Button Color Bleed on Hover

### The Problem

When styling QPushButton with `border-radius` and hover effects in dark themes, you may see unwanted color bleeding (e.g., purple artifacts) around the button edges. This happens because:

1. The `background` property doesn't fully override inherited styles
2. Transparent borders create anti-aliasing artifacts that leak parent container colors
3. Qt's CSS cascade isn't as predictable as web CSS

### The Solution

**Always use `background-color` instead of `background`, and always define explicit solid borders:**

```python
button.setStyleSheet(f"""
    QPushButton {{
        background-color: {color};          # Use background-color, NOT background
        color: {text_color};
        border: 2px solid {solid_color};    # Always solid, never 'none' or transparent
        border-radius: 6px;
        padding: 12px 32px;
        font-size: 14px;
        font-weight: bold;
    }}
    QPushButton:hover {{
        background-color: {hover_color};    # Use background-color for hover too
        border: 2px solid {hover_border};
    }}
    QPushButton:pressed {{
        background-color: {pressed_color};
        border: 2px solid {pressed_border};
    }}
    QPushButton:disabled {{
        background-color: {disabled_bg};
        color: {disabled_text};
        border: 2px solid {disabled_border};  # Solid border even when disabled
    }}
""")
```

### Why This Works

1. **`background-color`** directly sets the background without affecting other background properties like images or gradients that might be inherited
2. **Solid borders** prevent transparency from leaking parent container colors through anti-aligned edges
3. **Explicit color values** in all states (normal, hover, pressed, disabled) prevent Qt from interpolating between undefined states

### Common Mistakes

```python
# ❌ Wrong - causes color bleed
QPushButton {{
    background: {color};        # Too broad, inherits styles
    border: none;               # Transparent border leaks colors
    border-radius: 6px;         # Anti-aliased edges show through
}}
QPushButton:hover {{
    background: {hover_color}dd;  # Semi-transparent alpha makes it worse
}}

# ✅ Correct - solid boundaries
QPushButton {{
    background-color: {color};
    border: 2px solid {color};
    border-radius: 6px;
}}
QPushButton:hover {{
    background-color: {hover_color};  # Solid color
    border: 2px solid {hover_border}; # Solid border
}}
```

## Other PyQt5 Dark Theme Gotchas

### 1. Invisible Text on QSpinBox

```python
# Problem: Text disappears in dark mode
spin_box.setStyleSheet("""
    QSpinBox {
        background-color: #2c2c2c;
        color: white;
    }
""")

# Solution: Set palette explicitly
palette = QPalette()
palette.setColor(QPalette.Base, QColor("#2c2c2c"))
palette.setColor(QPalette.Text, QColor("#ffffff"))
spin_box.setPalette(palette)
```

### 2. QComboBox Dropdown Inheritance

```python
# Problem: Dropdown inherits light theme colors
combo.setStyleSheet("""
    QComboBox { background: dark; color: white; }
""")

# Solution: Style QComboBox::drop-down and QComboBox QAbstractItemView separately
combo.setStyleSheet("""
    QComboBox {
        background-color: #2c2c2c;
        color: white;
        border: 1px solid #444;
    }
    QComboBox::drop-down {
        border: none;
    }
    QComboBox QAbstractItemView {
        background-color: #2c2c2c;
        color: white;
        selection-background-color: #444;
    }
""")
```

### 3. QGroupBox Title Invisibility

```python
# Problem: GroupBox title blends into background
group_box.setStyleSheet("""
    QGroupBox {
        background-color: #1a1a1a;
        border: 1px solid #444;
    }
""")

# Solution: Explicitly style the title
group_box.setStyleSheet("""
    QGroupBox {
        background-color: #1a1a1a;
        border: 1px solid #444;
        border-radius: 4px;
        margin-top: 1em;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        subcontrol-position: top center;
        color: white;
        padding: 0 5px;
    }
""")
```

### 4. QProgressBar Chunk Disappears

```python
# Problem: Progress bar fills with solid color only
progress_bar.setStyleSheet("""
    QProgressBar {
        background: #2c2c2c;
    }
    QProgressBar::chunk {
        background: #4CAF50;
    }
""")

# Solution: Use background-color and ensure chunk has height
progress_bar.setStyleSheet("""
    QProgressBar {
        background-color: #2c2c2c;
        border: 1px solid #444;
        border-radius: 4px;
        text-align: center;
        color: white;
    }
    QProgressBar::chunk {
        background-color: #4CAF50;
        border-radius: 3px;
    }
""")
```

## Testing Pattern

When debugging PyQt5 dark theme issues:

1. **Start with explicit colors**: Don't rely on inheritance
2. **Test all states**: normal, hover, pressed, disabled, focused
3. **Check borders**: Use solid borders first, then experiment with transparency
4. **Use Qt Designer**: Generate base styles and inspect the XML
5. **Screenshot comparison**: Dark themes look different on different displays

## Quick Reference

| Property | Avoid | Use Instead |
|----------|-------|-------------|
| `background` | ❌ | `background-color` ✅ |
| `border: none` | ❌ | `border: 2px solid {color}` ✅ |
| `color: {color}88` (semi-transparent) | ❌ | Solid `color: {color}` ✅ |
| `background: {color}dd` (semi-transparent) | ❌ | Solid `background-color: {color}` ✅ |
| Implicit inheritance | ❌ | Explicit all states ✅ |

## Related Skills

- `gui-document-access-git` - Git access in GUI applications
- `pyqt-subprocess-integration` - Running CLI commands from PyQt5 GUIs

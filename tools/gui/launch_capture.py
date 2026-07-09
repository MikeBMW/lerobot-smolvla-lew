#!/usr/bin/env python3
"""启动Z-MAX Studio并自动截图"""
import sys, os, time
os.environ['PYTHONPATH'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../src')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import the studio module
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../src'))

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer

# Create app and main window
app = QApplication(sys.argv)

# Monkey-patch studio main to capture screenshot after launch
import studio
studio.main_mod = studio

# Override main to capture screenshot
orig_main = studio.main
def new_main():
    orig_main()
    # Wait 3 seconds for rendering, then capture
    def capture():
        from PyQt5.QtWidgets import QWidget
        for w in QApplication.allWidgets():
            if w.isWindow() and w.windowTitle():
                pixmap = w.grab()
                pixmap.save('/Users/mikeni/zmax_gui_window.png', 'PNG')
                print(f'Captured window: {w.windowTitle()} {pixmap.size().width()}x{pixmap.size().height()}')
                break
        else:
            print('No window found!')
        # Don't quit - keep GUI running
    QTimer.singleShot(3000, capture)

studio.main = new_main
studio.main()

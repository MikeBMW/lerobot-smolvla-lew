#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""yolo_label_widget.py — 可拖框的标定画面控件 (给「输入图像」窗口用)

老倪 2026-09-17: 「在右键打开的窗口增加标定功能, 让标定工程师根据图像圈选光模块、输入类别、
保存当前图片, 而且 YOLO 模型可以通过保存的图片进行模型训练」

职责边界 (单一真相):
  · **框永远以"原始帧像素坐标"存储** (x1,y1,x2,y2) —— 与训练图片同一坐标系;
  · 显示可以按 rot_deg 旋转 (相机翻转时工程师在旋转画面上更看得清), 旋转只影响**显示**,
    从旋转画面拖出的框会**自动换算回原始帧坐标**再入列 (避免"在旋转窗标注 → 标签镜像"的脏数据);
  · 一帧一控件: `set_frame_rgb()` 喂帧, `boxes()` 取框, 保存交给 yolo_annot_dataset.save_sample。

交互: 左键拖 = 新建框 · 拖动框内 = 移动 · 拖四角 = 缩放 · 右键框内 = 删除 · Del = 删选中
      Ctrl+Z = 撤销 · Esc = 取消选中/放弃当前拖框 · 双击框 = 选中并可在外部改类别
API (取证/半自动预标注可直接调): set_frame_rgb / boxes / set_boxes / add_box_px / remove_selected /
      clear_boxes / undo / set_editable / set_current_class / set_classes / pixmap
"""
from __future__ import annotations

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets

# 类别配色 (按 class id 轮转; 单色底 + 高对比边框, 老倪偏好: 勿多色彩高亮)
_PALETTE = [(0, 212, 170), (31, 111, 235), (212, 168, 0), (163, 113, 247),
            (240, 136, 62), (255, 99, 132), (200, 200, 200)]


def map_pt(x, y, deg, W, H):
    """原始帧点 → 显示点 (deg∈{0,90,180,270}; 与 QTransform().rotate(deg) 同向)"""
    if deg == 0:
        return x, y
    if deg == 180:
        return W - 1 - x, H - 1 - y
    if deg == 90:
        return H - 1 - y, x
    if deg == 270:
        return y, W - 1 - x
    raise ValueError(deg)


def unmap_pt(x, y, deg, W, H):
    """显示点 → 原始帧点 (逆变换; 90↔270 互为逆, 0/180 自逆)"""
    inv = {0: 0, 180: 180, 90: 270, 270: 90}[deg]
    dW, dH = disp_size(deg, W, H)
    return map_pt(x, y, inv, dW, dH)


def disp_size(deg, W, H):
    return (W, H) if deg in (0, 180) else (H, W)


def map_box(box, deg, W, H):
    """框 (原始) ↔ (显示): 两角映射后归一化 —— 正反变换同一函数 (deg 与逆角)"""
    x1, y1, x2, y2 = box
    a = map_pt(x1, y1, deg, W, H)
    b = map_pt(x2, y2, deg, W, H)
    return min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])


def unmap_box(box, deg, W, H):
    x1, y1, x2, y2 = box
    inv = {0: 0, 180: 180, 90: 270, 270: 90}[deg]
    dW, dH = disp_size(deg, W, H)
    a = map_pt(x1, y1, inv, dW, dH)
    b = map_pt(x2, y2, inv, dW, dH)
    return min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])


class YoloLabelWidget(QtWidgets.QWidget):
    """一帧 + 若干框 (框用原始帧像素坐标)"""

    changed = QtCore.pyqtSignal()                    # 框集合变化 (外部刷新列表/状态行)
    selectionChanged = QtCore.pyqtSignal(int)        # 选中索引 (-1 = 无)
    cursorMoved = QtCore.pyqtSignal(float, float)    # 鼠标在**原始帧**里的坐标

    def __init__(self, parent=None, rot_deg: int = 0, editable: bool = False):
        super().__init__(parent)
        self.setObjectName("img")
        self.setMinimumSize(320, 240)
        self.setMouseTracking(True)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.rot_deg = int(rot_deg)
        self._rgb = None                             # 原始帧 (HxWx3 uint8, **不旋转**)
        self._pm_orig = None                         # 原始帧 QPixmap (缓存, 不重复解码)
        self._boxes = []                             # [{'box':(x1,y1,x2,y2), 'cls':str}]
        self._sel = -1
        self._undo = []
        self._editable = bool(editable)
        self._cls = "peg"                            # 新建框的类别 (口径: 见 frame_source.py CLASS_MAP peg→光模块)
        self._classes = ["peg"]
        self._drag = None                            # ('new'|'move'|'resize', 角, 起点...)
        self._hit = None
        # 显示几何 (paintEvent 里算好后, 鼠标事件用同一套 → 像素映射严格一致)
        self._scale = 1.0
        self._off = (0.0, 0.0)
        self._cur_img_pt = None
        self.setToolTip("标定模式: 左键拖出框 · 拖框内=移动 · 拖角=缩放 · 右键框内=删除 · Del=删选中")

    # ── 数据 ──────────────────────────────────────────────────────────
    def set_frame_rgb(self, rgb):
        """喂一帧 (原始朝向的 RGB uint8); 显示时按 rot_deg 旋转"""
        if rgb is None:
            return
        self._rgb = np.ascontiguousarray(rgb)
        h, w = self._rgb.shape[:2]
        img = QtGui.QImage(bytes(self._rgb.data), w, h, 3 * w, QtGui.QImage.Format_RGB888)
        pm = QtGui.QPixmap.fromImage(img)
        if self.rot_deg:
            pm = pm.transformed(QtGui.QTransform().rotate(self.rot_deg), QtCore.Qt.SmoothTransformation)
        self._pm_orig = pm
        self.update()

    def frame_rgb(self):
        return self._rgb

    def pixmap(self):
        """兼容旧取证/调用: 返回当前显示用的 QPixmap (已按 rot_deg 旋转, 未缩放)"""
        return self._pm_orig

    def boxes(self):
        return [dict(b, box=tuple(b["box"])) for b in self._boxes]

    def boxes_px(self):
        return [(b["box"][0], b["box"][1], b["box"][2], b["box"][3], b["cls"]) for b in self._boxes]

    def set_boxes(self, boxes):
        """boxes: [(x1,y1,x2,y2,cls) ...] (原始帧像素坐标)"""
        self._push_undo()
        self._boxes = [{"box": (float(b[0]), float(b[1]), float(b[2]), float(b[3])), "cls": b[4]}
                       for b in boxes]
        self._sel = len(self._boxes) - 1 if self._boxes else -1
        self._emit()

    def add_box_px(self, box, cls=None):
        self._push_undo()
        self._boxes.append({"box": tuple(float(v) for v in box[:4]),
                            "cls": cls if cls is not None else self._cls})
        self._sel = len(self._boxes) - 1
        self._emit()

    def remove_selected(self):
        if 0 <= self._sel < len(self._boxes):
            self._push_undo()
            self._boxes.pop(self._sel)
            self._sel = min(self._sel, len(self._boxes) - 1)
            self._emit()

    def clear_boxes(self):
        if self._boxes:
            self._push_undo()
            self._boxes = []
            self._sel = -1
            self._emit()

    def undo(self):
        if self._undo:
            self._boxes, self._sel = self._undo.pop()
            self._emit()

    def set_selected_class(self, cls):
        if 0 <= self._sel < len(self._boxes):
            self._push_undo()
            self._boxes[self._sel]["cls"] = cls
            self._emit()

    def selected(self):
        return self._sel if 0 <= self._sel < len(self._boxes) else -1

    def set_current_class(self, cls):
        self._cls = cls

    def set_classes(self, names):
        self._classes = list(names)

    def set_editable(self, on):
        self._editable = bool(on)
        self.setCursor(QtCore.Qt.CrossCursor if on else QtCore.Qt.ArrowCursor)
        self.update()

    def set_rot_deg(self, deg):
        self.rot_deg = int(deg)
        if self._rgb is not None:
            self.set_frame_rgb(self._rgb)            # 重生成显示 pixmap (框不变, 仍是原始坐标)

    # ── 内部 ─────────────────────────────────────────────────────────
    def _push_undo(self):
        self._undo.append(([dict(b) for b in self._boxes], self._sel))
        self._undo[:] = self._undo[-30:]

    def _emit(self):
        self.update()
        self.changed.emit()
        self.selectionChanged.emit(self._sel)

    def _geom(self):
        """返回 (scale, ox, oy, dispW, dispH): 等比居中铺满控件"""
        if self._pm_orig is None or self._pm_orig.isNull():
            return 1.0, 0.0, 0.0, 0, 0
        dw, dh = self._pm_orig.width(), self._pm_orig.height()
        s = min(self.width() / max(1, dw), self.height() / max(1, dh))
        return s, (self.width() - dw * s) / 2.0, (self.height() - dh * s) / 2.0, dw, dh

    def _to_img(self, pos):
        s, ox, oy, dw, dh = self._geom()
        if s <= 0:
            return None
        return (pos.x() - ox) / s, (pos.y() - oy) / s          # 显示坐标 (disp 空间)

    def _hit_test(self, img_pt):
        """img_pt 是显示空间点; 返回 ('move'|'resize-tl|tr|bl|br', idx) 或 (None, -1)"""
        if img_pt is None or self._rgb is None:
            return None, -1
        W, H = self._rgb.shape[1], self._rgb.shape[0]
        s, _, _, _, _ = self._geom()
        tol = max(4.0, 6.0 / max(s, 1e-6))                     # 角命中容差 (像素)
        px, py = img_pt
        for i in range(len(self._boxes) - 1, -1, -1):
            bx = map_box(self._boxes[i]["box"], self.rot_deg, W, H)
            x1, y1, x2, y2 = bx
            for name, (cx, cy) in (("tl", (x1, y1)), ("tr", (x2, y1)),
                                   ("bl", (x1, y2)), ("br", (x2, y2))):
                if abs(px - cx) <= tol and abs(py - cy) <= tol:
                    return "resize-" + name, i
            if x1 <= px <= x2 and y1 <= py <= y2:
                return "move", i
        return None, -1

    # ── 绘制 ─────────────────────────────────────────────────────────
    def paintEvent(self, ev):                                          # noqa: N802
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor("#161b22"))
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        if self._pm_orig is None or self._pm_orig.isNull():
            p.setPen(QtGui.QColor("#8b949e"))
            p.drawText(self.rect(), QtCore.Qt.AlignCenter, "等待输入帧…")
            return
        s, ox, oy, dw, dh = self._geom()
        self._scale, self._off = s, (ox, oy)
        p.drawPixmap(QtCore.QRectF(ox, oy, dw * s, dh * s), self._pm_orig, QtCore.QRectF(self._pm_orig.rect()))
        W, H = (self._rgb.shape[1], self._rgb.shape[0]) if self._rgb is not None else (dw, dh)
        for i, b in enumerate(self._boxes):
            bx = map_box(b["box"], self.rot_deg, W, H)
            x1, y1, x2, y2 = [v * s for v in bx]
            x1, y1 = x1 + ox, y1 + oy
            x2, y2 = x2 + ox, y2 + oy
            cid = self._classes.index(b["cls"]) if b["cls"] in self._classes else 0
            col = QtGui.QColor(*_PALETTE[cid % len(_PALETTE)])
            sel = (i == self._sel)
            pen = QtGui.QPen(col, 3 if sel else 2)
            if sel:
                pen.setStyle(QtCore.Qt.SolidLine)
            p.setPen(pen)
            p.drawRect(QtCore.QRectF(x1, y1, x2 - x1, y2 - y1))
            if sel:                                            # 选中: 四角把手
                p.setBrush(col)
                for hx, hy in ((x1, y1), (x2, y1), (x1, y2), (x2, y2)):
                    p.drawRect(QtCore.QRectF(hx - 4, hy - 4, 8, 8))
                p.setBrush(QtCore.Qt.NoBrush)
            tag = f"{i+1}. {b['cls']}  {abs(b['box'][2]-b['box'][0]):.0f}x{abs(b['box'][3]-b['box'][1]):.0f}px"
            p.setFont(QtGui.QFont("Arial", 9))
            fm = p.fontMetrics()
            tw, th = fm.horizontalAdvance(tag) + 8, fm.height() + 2
            ty = y1 - th - 1 if y1 - th - 1 > 0 else y2 + 1
            p.fillRect(QtCore.QRectF(x1, ty, tw, th), QtGui.QColor(13, 17, 23, 225))
            p.setPen(col)
            p.drawText(QtCore.QRectF(x1 + 4, ty, tw, th), QtCore.Qt.AlignVCenter, tag)
        if self._drag and self._drag[0] == "new":              # 拖拽中的橡皮筋
            a = self._drag[1]
            b = self._to_img(self.mapFromGlobal(QtGui.QCursor.pos()))
            if b is not None:
                p.setPen(QtGui.QPen(QtGui.QColor("#00d4aa"), 1, QtCore.Qt.DashLine))
                p.drawRect(QtCore.QRectF(min(a[0], b[0]) * s + ox, min(a[1], b[1]) * s + oy,
                                         abs(a[0] - b[0]) * s, abs(a[1] - b[1]) * s))
        # 底部信息条 (自解释: 分辨率/缩放/鼠标位置/框数)
        info = f"{W}x{H} · 显示 {dw}x{dh} · 缩放 {s:.2f}x · 框 {len(self._boxes)} 个"
        if self._cur_img_pt is not None:
            info += f" · 鼠标 ({self._cur_img_pt[0]:.0f},{self._cur_img_pt[1]:.0f})"
        if self._editable:
            info += f" · ✏️ 标定中 (新框类别: {self._cls})"
        p.setPen(QtGui.QColor("#e6edf3"))
        p.fillRect(QtCore.QRectF(0, self.height() - 18, self.width(), 18), QtGui.QColor(13, 17, 23, 200))
        p.drawText(QtCore.QRectF(4, self.height() - 18, self.width(), 18), QtCore.Qt.AlignVCenter, info)

    # ── 鼠标/键盘 ────────────────────────────────────────────────────
    def _img_pt_from_event(self, ev):
        pt = self._to_img(ev.pos())
        if pt is None or self._rgb is None:
            return None
        W, H = self._rgb.shape[1], self._rgb.shape[0]
        if not (0 <= pt[0] <= W and 0 <= pt[1] <= H):
            return None
        return pt

    def mousePressEvent(self, ev):                                     # noqa: N802
        if not self._editable:
            return super().mousePressEvent(ev)
        pt = self._img_pt_from_event(ev)
        if pt is None:
            return
        kind, idx = self._hit_test(pt)
        self.setFocus()
        if ev.button() == QtCore.Qt.RightButton:
            if idx >= 0:
                self._sel = idx
                self.remove_selected()
            return
        if kind == "move" or (kind or "").startswith("resize"):
            self._sel = idx
            self._drag = (kind, self._boxes[idx]["box"], pt, idx)
            self._push_undo()
            self._emit()
            return
        self._drag = ("new", pt, pt, -1)
        self._sel = -1
        self._emit()

    def mouseMoveEvent(self, ev):                                      # noqa: N802
        pt = self._img_pt_from_event(ev)
        if pt is not None and self._rgb is not None:
            ox, oy = unmap_pt(pt[0], pt[1], self.rot_deg, self._rgb.shape[1], self._rgb.shape[0])
            self._cur_img_pt = (float(ox), float(oy))
            self.cursorMoved.emit(float(ox), float(oy))
        if self._edit_drag(pt) or self._editable:
            self.update()
        else:
            super().mouseMoveEvent(ev)

    def _edit_drag(self, pt):
        if not self._editable or self._drag is None or pt is None:
            return False
        kind, box, start, idx = self._drag
        W, H = self._rgb.shape[1], self._rgb.shape[0]
        if kind == "new":
            # 🐛 2026-09-17 老倪「左键拖不出框」根因: 原来写成 ("new", start, pt, -1) ——
            #   start 是"上一次鼠标移动点", 每动一次就把**按下锚点覆盖掉** ⇒ 松开时
            #   算出的矩形只剩最后一小段位移(通常 <4px) → 被当成误点丢弃 (或拖出个小碎片框)。
            #   锚点必须恒为按下那一点 (index1), index2 才跟随鼠标。
            self._drag = ("new", box, pt, -1)
            self.update()
            return True
        # move / resize 在显示空间算, 结束再映射回原始
        dbox = map_box(box, self.rot_deg, W, H)
        dx, dy = pt[0] - start[0], pt[1] - start[1]
        x1, y1, x2, y2 = dbox
        if kind == "move":
            nx1, ny1, nx2, ny2 = x1 + dx, y1 + dy, x2 + dx, y2 + dy
        else:
            nx1, ny1, nx2, ny2 = x1, y1, x2, y2
            if kind.endswith("tl"):
                nx1, ny1 = pt[0], pt[1]
            elif kind.endswith("tr"):
                nx2, ny1 = pt[0], pt[1]
            elif kind.endswith("bl"):
                nx1, ny2 = pt[0], pt[1]
            else:
                nx2, ny2 = pt[0], pt[1]
        self._boxes[idx]["box"] = unmap_box((nx1, ny1, nx2, ny2), self.rot_deg, W, H)
        self._drag = (kind, self._boxes[idx]["box"], pt, idx)
        self.update()
        return True

    def mouseReleaseEvent(self, ev):                                   # noqa: N802
        if not self._editable or self._drag is None:
            return super().mouseReleaseEvent(ev)
        kind, box, start, idx = self._drag
        self._drag = None
        if kind == "new":
            x1, y1, x2, y2 = min(start[0], box[0]), min(start[1], box[1]), max(start[0], box[0]), max(start[1], box[1])
            if (x2 - x1) < 4 or (y2 - y1) < 4:              # 误点 → 只取消选中
                self._sel = -1
                self._emit()
                return
            self._boxes.append({"box": unmap_box((x1, y1, x2, y2), self.rot_deg,
                                                 self._rgb.shape[1], self._rgb.shape[0]), "cls": self._cls})
            self._sel = len(self._boxes) - 1
        elif kind == "move":
            self._sel = idx
        self._emit()

    def keyPressEvent(self, ev):                                       # noqa: N802
        if not self._editable:
            return super().keyPressEvent(ev)
        k = ev.key()
        if k in (QtCore.Qt.Key_Delete, QtCore.Qt.Key_Backspace):
            self.remove_selected()
        elif k == QtCore.Qt.Key_Z and (ev.modifiers() & QtCore.Qt.ControlModifier):
            self.undo()
        elif k == QtCore.Qt.Key_Escape:
            self._drag = None
            self._sel = -1
            self._emit()
        elif QtCore.Qt.Key_1 <= k <= QtCore.Qt.Key_9:
            i = k - QtCore.Qt.Key_1
            if i < len(self._classes):
                self.set_current_class(self._classes[i])
                self.set_selected_class(self._classes[i])
        else:
            return super().keyPressEvent(ev)

    def resizeEvent(self, ev):                                         # noqa: N802
        super().resizeEvent(ev)
        self.update()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运行期文本体检 (只读): 把 **有运行状态** 的节点 (L5 闭环节点 / 能力档位 L5 进度) 参数
塞满长中文后再用代理画笔量一遍 —— 这是老倪现场看到"字只有一半"的真实工况
(离线审计只看静态 JSON, 看不到 l5_lines 这类运行期串)。

用法: QT_QPA_PLATFORM=offscreen [ZMAX_NODE_PX_SCALE=1.15] gui-venv311/bin/python /tmp/node_runtime_text_check.py
"""
import json
import os
import sys

sys.path.insert(0, "/home/ubuntu/zmax_rel/tools/gui")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QRectF, Qt  # noqa: E402
from PyQt5.QtGui import QImage, QPainter, QColor  # noqa: E402
from PyQt5.QtWidgets import QApplication, QStyleOptionGraphicsItem  # noqa: E402

app = QApplication.instance() or QApplication([])
import simulink_module as SM  # noqa: E402

FLOW = "/home/ubuntu/zmax_rel/flows/state_space_obs.json"
d = json.load(open(FLOW, encoding="utf-8"))
nodes = d["nodes"]
shim = type("S", (), {"nodes": nodes, "links": d.get("links", [])})()

LONG = [
    "自动标注: 6 路相机 → VLM 逐帧打标 (已 1284/2400 帧, 预计 18 分钟)",
    "监督训练: L2 全量 12.4k 帧 → L3/L4 LoRA → merge 回主干 (阶段 2/4)",
    "产物: /home/ubuntu/zmax_rel/outputs/l5_auto/ckpt_step_3200.pt · 评测成功率 0.93",
]


class P:
    def __init__(self, real):
        self._r = real
        self.ops = []

    def __getattr__(self, k):
        return getattr(self._r, k)

    def fontMetrics(self):
        return self._r.fontMetrics()

    def font(self):
        return self._r.font()

    def _key(self, o):
        return (round(o.x(), 1), round(o.y(), 1), round(o.width(), 1), round(o.height(), 1)) if isinstance(o, QRectF) else None

    def drawText(self, *a):
        t = a[-1] if isinstance(a[-1], str) else ""
        self.ops.append((self._key(a[0]), round(self._r.fontMetrics().horizontalAdvance(t), 1), round(self._r.font().pixelSize() if self._r.font().pixelSize() > 0 else self._r.font().pointSizeF(), 1), t))
        return self._r.drawText(*a)

    def drawRoundedRect(self, *a):
        self.ops.append(("FILL", self._key(a[0]) or self._key(a[1])))
        return self._r.drawRoundedRect(*a)

    def drawRect(self, *a):
        self.ops.append(("FILL", self._key(a[0]) or self._key(a[1])))
        return self._r.drawRect(*a)

    def drawEllipse(self, *a):
        self.ops.append(("FILL", self._key(a[0]) or self._key(a[1])))
        return self._r.drawEllipse(*a)


def check(node, tag):
    w, h = int(node.get("w", SM.DW)), int(node.get("h", SM.DH))
    img = QImage(w + 8, h + 8, QImage.Format_ARGB32)
    img.fill(QColor("#0a0a0f"))
    real = QPainter(img)
    real.setRenderHint(QPainter.Antialiasing)
    real.translate(4, 4)
    p = P(real)
    it = SM.SimNodeItem(node, shim)
    try:
        it.paint(p, QStyleOptionGraphicsItem(), None)
    except Exception as e:
        print("  paint 异常", e)
    real.end()
    bad = []
    for i, o in enumerate(p.ops):
        if not isinstance(o[0], tuple):
            continue
        r, tw, px, txt = o
        if tw > r[2] + 1.0:
            bad.append(("超框(会被裁)", txt[:26], f"宽{tw}>{r[2]} @ p{px}"))
        if r[0] + r[2] > w + 1 or r[1] + r[3] > h + 1:
            bad.append(("画到框外", txt[:26], f"rect {r} 框 {w}x{h}"))
    print(f"[{tag}] {w}x{h} 文字 {sum(1 for o in p.ops if isinstance(o[0], tuple))} 条 → "
          + ("✅ 全部放得下" if not bad else f"❌ {len(bad)} 处"))
    for b in bad[:8]:
        print("     ", b[0], "|", b[1], "|", b[2])
    return len(bad)


tot = 0
hits = [n for n in nodes if "视觉语言自动标注" in str(n.get("name", ""))]
for n in hits:
    n2 = json.loads(json.dumps(n))
    n2.setdefault("params", {})["l5_loop"] = True
    n2["params"]["l5_lines"] = LONG
    n2["params"]["l5_state"] = "running"
    tot += check(n2, "L5 闭环(运行中, 3 行长中文)")
    n3 = json.loads(json.dumps(n))
    n3.setdefault("params", {})["l5_loop"] = True
    n3["params"]["l5_lines"] = ["❌ 失败: FileNotFoundError: /home/ubuntu/zmax_rel/datasets/l5_auto_annotations.parquet (缺数据, 请先导出)", ""]
    n3["params"]["l5_state"] = "error"
    tot += check(n3, "L5 闭环(报错, 超长行)")
for n in [x for x in nodes if (x.get("params") or {}).get("cap_switch")]:
    for lvl in ("L2", "L5"):
        n2 = json.loads(json.dumps(n))
        n2["params"]["cap_level"] = lvl
        n2["params"]["l5_lines"] = LONG[:2]
        n2["params"]["l5_state"] = "running"
        tot += check(n2, f"能力档位(档={lvl} + 2 行进度)")
print(("✅ 运行期文本全部放得下" if tot == 0 else f"❌ 共 {tot} 处"), "| 字号倍率 =", os.environ.get("ZMAX_NODE_PX_SCALE", "1.0"))
sys.stdout.flush()

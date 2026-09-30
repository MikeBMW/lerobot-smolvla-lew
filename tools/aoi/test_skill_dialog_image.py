#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_skill_dialog_image.py — 离屏验证: 技能清单预览能按"技能自己的 URL"出图 (表面通道)

起因 (老倪): "先把当前的表面检测做成技能, 而且也要看到图片"
做法: 起一个本地 http.server 冒充 10083 的 /picture, 把 surface v4 离线生成的 1280 方图喂进去,
      离屏构造 L2SkillDialog → _refresh_image(url=...) → 断言 pixmap 真加载、标签含 1280x1280。
      另测 _skill_image_url() 对各类技能的推断 (图像类用自身URL; 触发/判决类回落同通道 /picture?kind=crop)。
用法: QT_QPA_PLATFORM=offscreen gui-venv311/bin/python /home/ubuntu/aoi_v4/test_skill_dialog_image.py
"""
import os
import sys
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = "/home/ubuntu/lerobot-smolvla-lew"
SURF_DIR = "/home/ubuntu/aoi_v4/surface_images"
sys.path.insert(0, os.path.join(REPO, "tools", "gui"))
sys.path.insert(0, os.path.join(REPO, "src"))

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer   # noqa: E402

from PyQt5.QtWidgets import QApplication                                # noqa: E402


def serve(directory, port=8899):
    class H(SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=directory, **k)

        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main():
    srv = serve(SURF_DIR)
    app = QApplication(sys.argv)
    import l2_skill_dialog as D

    dlg = D.L2SkillDialog()
    ok = True

    # ① 按技能自身 URL 拉图 (冒充 10083/picture?kind=crop) —— 取"规范图"(Letterbox 1280)那张
    png = sorted(f for f in os.listdir(SURF_DIR) if f.endswith(".png") and "Letterbox" in f)[0]
    dlg._refresh_image(url="http://127.0.0.1:8899/" + png, label="表面②检测图(1280方图)")
    txt = dlg.lbl_img.text()
    pm = dlg.img.pixmap()
    got = bool(pm and not pm.isNull())
    print("① 技能自带 URL 出图  → 标签=%r  pixmap=%s" % (txt, (pm.width(), pm.height()) if got else "空"))
    ok &= got and ("1280x1280" in txt)

    # ② _skill_image_url 推断
    cases = [
        {"id": "L2.aoi_surface_picture", "name": "📷 表面②检测图", "kind": "image",
         "url": "http://192.168.23.23:10083/picture", "query": "?kind=crop"},
        {"id": "L2.aoi_surface", "name": "🎯 表面①触发拍照检测", "ros": "http",
         "url": "http://192.168.23.23:10083/capture_detect"},
        {"id": "L2.aoi_gold_result", "name": "📝 金手指⑧判决", "ros": "http",
         "url": "http://192.168.23.23:10082/last_result"},
        {"id": "L2.aoi_gold_align", "name": "🛠 金手指⑦对准", "ros": "script",
         "script": "tools/aoi_gold_servo.py"},
    ]
    for s in cases:
        u, lab = dlg._skill_image_url(s)
        print("② %-24s → %s" % (s["id"], u))
        if s["id"].startswith("L2.aoi_surface") or s["id"] == "L2.aoi_gold_result":
            ok &= bool(u) and "/picture?kind=crop" in u

    # ③ 全技能清单能加载 (注册表 29 条)
    print("③ 技能清单条数 =", dlg.lst.count())
    ok &= dlg.lst.count() >= 29

    srv.shutdown()
    print("\n" + ("✅ 技能清单预览(含表面通道)验证通过" if ok else "❌ 有断言失败"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""真机标定烟雾测试 (管线可训练性验证, 非精度验证):
用**真机 D405 实时帧** → 走真标定保存路径 (yolo_annot_dataset.save_sample) → 构建数据集 → 体检。
⚠️ 这里的框是**程序化占位框** (覆盖画面下方正中区域, 老倪说光模块就在那儿), 不是人工精标 →
   只证明"真机帧 → 标定 → 数据集 → 能训练"这条管线通, 精度必须靠人工标定。
数据根: /home/ubuntu/zmax_data/annot_smoke (独立于用户的 data/yolo_annot, 不污染)
"""
import json
import os
import shutil
import sys
import time

ROOT = "/home/ubuntu/lerobot-smolvla-lew"
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
import numpy as np                                                            # noqa: E402
import yolo_annot_dataset as yad                                              # noqa: E402
import yolo_input_viewer as yiv                                               # noqa: E402

SMOKE = "/home/ubuntu/zmax_data/annot_smoke"
LIVE_JPG, LIVE_META = yiv.LIVE_JPG, yiv.LIVE_META

# 需要就自己把链路拉起来 (控制台窗口没开时 live_frame.jpg 是旧帧) —— 采完自动收口
WITH_CHAIN = "--with-chain" in sys.argv
if WITH_CHAIN:
    print("拉起链路:", yiv._RemoteChain.ensure())

if os.path.isdir(SMOKE):
    shutil.rmtree(SMOKE)
yad.ensure_layout(SMOKE)
yad.add_class(SMOKE, "optical_module")
print("数据根:", SMOKE, "| 类别:", yad.load_classes(SMOKE))

n, tried = 0, 0
seen_seq = set()
while n < 8 and tried < 120:
    tried += 1
    time.sleep(0.6)
    try:
        m = json.load(open(LIVE_META))
        if not m.get("ok") or (m.get("age_s") or 99) > 3.0:
            continue
        if m.get("seq") in seen_seq:
            continue
        rgb = yiv.rgb_from_file(LIVE_JPG)
        if rgb is None:
            continue
        seen_seq.add(m.get("seq"))
        h, w = rgb.shape[:2]
        j = 10 * (n % 3)                                     # 每帧微移, 避免样本完全雷同
        box = (0.30 * w - j, 0.71 * h - j, 0.70 * w + j, 0.97 * h + j)
        rec = yad.save_sample(SMOKE, rgb, [(box[0], box[1], box[2], box[3], "optical_module")],
                             device=m.get("device") or "", seq=m.get("seq"), ts=m.get("ts"),
                             src=m.get("src") or "uvc", session="smoke_real",
                             annotator="pipeline-smoke",
                             extra={"note": "程序化占位框 (管线验证, 非人工精标)",
                                    "frame_age_s": m.get("age_s")})
        n += 1
        print(f"  [{n}] seq={m.get('seq')} age={m.get('age_s')}s 尺寸 {w}x{h} 框 "
              f"({box[0]:.0f},{box[1]:.0f},{box[2]:.0f},{box[3]:.0f}) → {os.path.basename(rec['image'])}")
    except FileNotFoundError:
        continue                              # meta 是原子替换写盘: 极短窗口内可能读不到 → 重试, 别退出
    except Exception as e:                                                # noqa: BLE001
        print("  ⚠️", type(e).__name__, e)

print(f"\n保存 {n} 张 → ", end="")
st = yad.build_dataset(SMOKE, val_ratio=0.34, seed=0)
print(f"train={st['n_train']} val={st['n_val']} 框={st['n_boxes']} 类别={st['classes']}")
print("data.yaml:")
print("   " + open(os.path.join(SMOKE, "dataset", "data.yaml")).read().replace("\n", "\n   "))
r = yad.check_dataset(SMOKE, strict=True)
print(f"体检: 图 {r['n_images']} 标注 {r['n_labels']} 框 {r['n_boxes']} 错误 {r['errors']} 警告 {len(r['warnings'])}")
if WITH_CHAIN:
    yiv._RemoteChain.stop()
    print("链路已收口 (Orin 侧临时进程已停)")
print("✅ 真机帧标定管线就绪 →", SMOKE)

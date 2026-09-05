#!/usr/bin/env python3
"""检测视频 HUD 文字方向 — 8 种变换 OCR 对比 (2026-08-19)
用法: python3 ocr_dir_check.py <帧目录|帧png> [帧序号]
输出: 每个变换的 OCR 识别文本, 识别出真实词组 (如 TREND peg->hole) 的方向 = 字正方向
注意: score 接近时看完整文本判断, 别只看分数 (帧噪声会刷分)
前置: apt-get install -y tesseract-ocr tesseract-ocr-chi-sim
"""
import os, sys, subprocess, io
from PIL import Image

def ocr(img):
    """tesseract OCR, 返回 (文本, 平均置信度, 词数, 中文字数, 字母数字数)"""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    p = subprocess.run(["tesseract", "stdin", "stdout", "-l", "chi_sim+eng",
                        "--psm", "11", "tsv"],
                       input=buf.getvalue(), capture_output=True)
    txt = p.stdout.decode("utf-8", errors="replace")
    lines = txt.strip().splitlines()
    words, confs = [], []
    for ln in lines[1:]:
        parts = ln.split("\t")
        if len(parts) < 12:
            continue
        try:
            conf = float(parts[10])
        except ValueError:
            continue
        w = parts[11].strip()
        if w and conf > 0:
            words.append(w)
            confs.append(conf)
    text = " ".join(words)
    avg = sum(confs) / len(confs) if confs else 0.0
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    alnum = sum(1 for c in text if c.isalnum())
    return text, avg, len(words), cjk, alnum

def check_image(im, label="frame"):
    """对一张图测 4 旋转 × 2 镜像, 打印各方向 OCR 文本"""
    print(f"图: {label} ({im.size[0]}x{im.size[1]})\n{'='*70}")
    results = []
    for rot in (0, 90, 180, 270):
        for mir in (False, True):
            img = im.rotate(rot, expand=True)
            if mir:
                img = img.transpose(Image.FLIP_LEFT_RIGHT)
            text, avg, nw, cjk, alnum = ocr(img)
            score = cjk * 3 + alnum + nw * 2
            results.append((score, rot, mir, text))
            tag = f"rot{rot:>3} mir{'L' if mir else '-'}"
            print(f"[{tag}] score={score:>4} conf={avg:5.1f} 字={cjk} 词={nw}")
            print(f"    OCR: {text[:110]}")
    print("=" * 70)
    results.sort(key=lambda r: -r[0])
    _, rot, mir, text = results[0]
    print(f"\n🏆 字正方向: rot{rot} mir{'L' if mir else '-'} (score={results[0][0]})")
    print(f"    OCR: {text[:130]}")
    # ⚠️ 重要判据: 分数接近时 (差<10) 必须人工看完整文本 —
    #    识别出真实词组 (TREND peg->hole inserted / hand->光模块) 的方向才是真的正
    return rot, mir

def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "."
    idx = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    if os.path.isdir(src):
        files = sorted(f for f in os.listdir(src) if f.lower().endswith((".png", ".jpg")))
        if not files:
            print("目录无图片"); return 1
        f = files[min(idx, len(files) - 1)]
        im = Image.open(os.path.join(src, f)).convert("RGB")
        label = os.path.join(src, f)
    else:
        im = Image.open(src).convert("RGB")
        label = src
    check_image(im, label)
    return 0

if __name__ == "__main__":
    sys.exit(main())

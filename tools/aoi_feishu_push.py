#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aoi_feishu_push.py — 把 **工控机裁减后的图** 实时推到飞书 (2026-09-24 老倪)

老倪: 「检查飞书端的 gateway, 我从飞书发消息; 把裁减后的图片, 发给飞书。要实时的」

设计:
  · 发送通道**自换 token** (tenant_access_token 每次现取) → 不依赖 gateway 进程内的 token 缓存
    (gateway 报 99991663 Invalid access token 时本工具仍能发 — 见技能 feishu-gateway 的兜底口径)
  · 图片走 /open-apis/im/v1/images 上传拿 image_key → 再发 msg_type=image (文本工具只支持 text/media)
  · push_once(): 取工控机"最近一次拍照"的**裁减图** (?kind=topview) + 附带判决/裁减指标做说明文字
  · watch(): **轮询 /last_result 的文件名变化**判"有新拍照" → 有新图就推; **只读, 不触发拍照**
    (绝不为了推送去连拍产线; 新图来自产线 HMI 或窗口的 📸)

用法:
  python3 tools/aoi_feishu_push.py --once                 # 推当前最新裁减图
  python3 tools/aoi_feishu_push.py --watch                # 实时: 有新拍照就推 (默认 8s 轮询)
  python3 tools/aoi_feishu_push.py --once --ours          # 连我们自裁×2 的判据图一起发
  python3 tools/aoi_feishu_push.py --chat oc_xxx --once
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
DEFAULT_CHAT = "oc_c0b4048546145c5c581ddd1a9e8f565d"      # 静界群 (老倪在用)
STATE = os.path.join(ROOT, "reports", "aoi_feishu_push_state.json")


# ── 飞书底层 (自换 token) ───────────────────────────────────────────────
def load_env() -> dict:
    env = {}
    p = os.path.expanduser("~/.hermes/.env")
    if os.path.isfile(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


def _post(url, data=None, headers=None, raw=None, ctype=None, timeout=30):
    hdrs = dict(headers or {})
    if data is not None and "Content-Type" not in hdrs:
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=raw if raw is not None else
                                 (json.dumps(data).encode() if data is not None else None),
                                 headers=hdrs, method="POST")
    if ctype:
        req.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "body": e.read().decode()[:300]}
    except Exception as e:                                                 # noqa: BLE001
        return {"error": str(e)}


def token() -> str:
    env = load_env()
    aid, sec = env.get("FEISHU_APP_ID", ""), env.get("FEISHU_APP_SECRET", "")
    if not aid or not sec:
        return ""
    r = _post("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
              {"app_id": aid, "app_secret": sec})
    return r.get("tenant_access_token", "")


def send_text(text: str, chat_id: str = DEFAULT_CHAT, tok: str = "") -> dict:
    tok = tok or token()
    if not tok:
        return {"ok": False, "err": "token 获取失败 (.env 缺 FEISHU_APP_ID/SECRET?)"}
    r = _post("https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
              {"receive_id": chat_id, "msg_type": "text",
               "content": json.dumps({"text": text}, ensure_ascii=False)},
              {"Authorization": f"Bearer {tok}"})
    return {"ok": r.get("code") == 0, "code": r.get("code"), "msg": r.get("msg"),
            "message_id": (r.get("data") or {}).get("message_id"), "raw": None if r.get("code") == 0 else r}


def send_image(path: str, chat_id: str = DEFAULT_CHAT, tok: str = "", caption: str = "") -> dict:
    """上传图片 → 发 image 消息 (可带说明文字, 另发一条文本)。返回 {ok, image_key, message_id, caption_id}"""
    if not os.path.isfile(path):
        return {"ok": False, "err": f"图不存在: {path}"}
    tok = tok or token()
    if not tok:
        return {"ok": False, "err": "token 获取失败"}
    H = {"Authorization": f"Bearer {tok}"}
    # ① 上传图片 (multipart: image_type=message + image)
    b = "----zmaximg" + os.urandom(8).hex()
    fn = os.path.basename(path)
    with open(path, "rb") as f:
        body = f.read()
    raw = ((f"--{b}\r\nContent-Disposition: form-data; name=\"image_type\"\r\n\r\nmessage\r\n"
            f"--{b}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{fn}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n").encode() + body + f"\r\n--{b}--\r\n".encode())
    up = _post("https://open.feishu.cn/open-apis/im/v1/images", None,
               {**H, "Content-Type": f"multipart/form-data; boundary={b}"}, raw=raw, timeout=60)
    ik = (up.get("data") or {}).get("image_key")
    if not ik:
        return {"ok": False, "err": f"图片上传失败: {up}"}
    out = {"ok": False, "image_key": ik, "upload_code": up.get("code")}
    # ② 发图
    r = _post("https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
              {"receive_id": chat_id, "msg_type": "image",
               "content": json.dumps({"image_key": ik})}, H)
    out["ok"] = r.get("code") == 0
    out.update({"code": r.get("code"), "msg": r.get("msg"),
                "message_id": (r.get("data") or {}).get("message_id")})
    if not out["ok"]:
        out["err"] = str(r)[:200]
    # ③ 说明文字 (单独一条, 免得长文被 400)
    if caption:
        rc = send_text(caption, chat_id, tok)
        out["caption_id"] = rc.get("message_id")
        out["caption_ok"] = rc.get("ok")
    return out


# ── AOI: 取裁减图 + 说明 ────────────────────────────────────────────────
def _read_state() -> dict:
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                      # noqa: BLE001
        return {}


def _write_state(d: dict):
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
    except Exception:                                                      # noqa: BLE001
        pass


def _save_crop(rgb, tag: str) -> str:
    import cv2
    d = os.path.join(ROOT, "reports", "feishu_push")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f"{tag}_{time.strftime('%Y%m%d_%H%M%S')}.png")
    cv2.imwrite(p, cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    return p


def push_once(chat_id: str = DEFAULT_CHAT, include_ours: bool = False, cam: int = 1,
              grab: bool = False) -> dict:
    """推"最近一次拍照"的裁减图 (工控机 topview) + 判决/裁减指标说明。返回结果 dict。

    grab=True → **先真拍一张**再推 (工控机内存被清空/服务重启后需要; 这是真拍产线台, 需显式指定)。
    """
    import opt_camera_client as optc
    if grab:
        cap = optc.capture_detect(cam)
        time.sleep(1.6)                       # 等工控机异步落盘 (其自家检测 ~1.5s)
    lr = optc.last_result(cam)
    ci = optc.crop_info(cam) if cam == 1 else {}
    rgb, meta = optc.fetch_frame(cam, kind="topview", grab=False)
    if rgb is None:
        return {"ok": False, "err": f"取裁减图失败: {meta.get('err')}", "last_result": lr}
    p = _save_crop(rgb, f"topview_{optc.CAMERAS[cam]['name']}")
    import numpy as np
    import cv2
    g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    cap = (f"【AOI 裁减图】{optc.CAMERAS[cam]['name']}相机 ({optc.CAMERAS[cam]['model']})\n"
           f"图: {rgb.shape[1]}x{rgb.shape[0]} · 均值{g.mean():.0f} · 饱和{(g>=250).mean()*100:.1f}% "
           f"· 取图 {meta.get('ms', 0):.0f}ms\n"
           f"工控机判决: {lr.get('verdict')} · 缺陷 {lr.get('count')} · 推理 {lr.get('ms')}ms · 第{lr.get('n')}次\n"
           f"裁减: method={ci.get('method')} canonical={ci.get('canonical')} score={ci.get('score')} "
           f"angle={ci.get('angle')} {ci.get('crop_ms') and '%.0fms' % ci['crop_ms'] or ''}\n"
           f"文件: {str(lr.get('topview') or '').replace(chr(92), '/').split('/')[-1]}\n"
           f"推送时间 {time.strftime('%F %T')} (只读推送, 未触发拍照)")
    r = send_image(p, chat_id, caption=cap)
    r.update({"img": p, "shape": list(rgb.shape), "verdict": lr.get("verdict"),
              "count": lr.get("count"), "file": lr.get("topview")})
    if include_ours:
        try:
            import aoi_exposure_fix as aex
            org, _om = optc.fetch_frame(cam, kind="origin", grab=False)
            if org is not None:
                ours, mt = aex.clean_judge_frame(org, out=None, k=2.0)
                po = _save_crop(ours, "ours_judge")
                ro = send_image(po, chat_id, caption=f"【我们自裁判据图】原始图切过曝+短边×2 → "
                                                     f"{ours.shape[1]}x{ours.shape[0]} ({mt['stretch_desc']})")
                r["ours"] = {"ok": ro.get("ok"), "img": po, "shape": list(ours.shape)}
        except Exception as e:                                             # noqa: BLE001
            r["ours"] = {"ok": False, "err": f"{type(e).__name__}: {e}"}
    return r


def watch(chat_id: str = DEFAULT_CHAT, interval: float = 8.0, seconds: float = 0,
          include_ours: bool = False, cam: int = 1) -> int:
    """实时: 轮询 /last_result 的 topview 文件名, 一变就推该裁减图。**只读, 不触发拍照**。"""
    import opt_camera_client as optc
    st = _read_state()
    last = st.get("last_topview") or ""
    print(f"👀 实时监听 {optc.CAMERAS[cam]['name']} 相机新拍照 (每 {interval:.0f}s 轮询, 只读不拍照) → {chat_id}")
    t0 = time.time()
    n = 0
    while True:
        try:
            lr = optc.last_result(cam)
            cur = str(lr.get("topview") or "")
            if cur and cur != last:
                first = not last
                last = cur
                _write_state({"last_topview": cur, "ts": time.strftime("%F %T")})
                if first:
                    print(f"   (基准) {os.path.basename(cur.replace(chr(92), '/'))}")
                else:
                    r = push_once(chat_id, include_ours=include_ours, cam=cam)
                    n += 1
                    print(f"   [{time.strftime('%H:%M:%S')}] 新拍照 → 推送 {'✅' if r.get('ok') else '❌'} "
                          f"{os.path.basename(cur.replace(chr(92), '/'))} · 判决 {r.get('verdict')}")
        except Exception as e:                                             # noqa: BLE001
            print("   ⚠️", type(e).__name__, e)
        if seconds and (time.time() - t0) > seconds:
            break
        time.sleep(interval)
    print(f"停止: 共推送 {n} 张")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="把工控机裁减图推到飞书 (自换 token, 不依赖 gateway token)")
    ap.add_argument("--once", action="store_true", help="推当前最新裁减图")
    ap.add_argument("--watch", action="store_true", help="实时: 有新拍照就推")
    ap.add_argument("--ours", action="store_true", help="连我们自裁×2 判据图一起发")
    ap.add_argument("--chat", default=DEFAULT_CHAT)
    ap.add_argument("--cam", type=int, default=1)
    ap.add_argument("--interval", type=float, default=8.0)
    ap.add_argument("--seconds", type=float, default=0, help="watch 跑多久 (0=不限)")
    ap.add_argument("--text", default="", help="顺带发一条文本 (自检用)")
    ap.add_argument("--grab", action="store_true", help="先真拍一张再推 (工控机内存空时必须; 真拍产线台)")
    a = ap.parse_args()
    if a.text:
        print(json.dumps(send_text(a.text, a.chat), ensure_ascii=False)); 
    if a.watch:
        raise SystemExit(watch(a.chat, a.interval, a.seconds, a.ours, a.cam))
    if a.once or not (a.watch or a.text):
        r = push_once(a.chat, include_ours=a.ours, cam=a.cam, grab=a.grab)
        print(json.dumps(r, ensure_ascii=False, indent=1))
        raise SystemExit(0 if r.get("ok") else 1)

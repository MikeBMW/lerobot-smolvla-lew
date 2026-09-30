#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同源闸: 证明"能点开的那张图"就是"喂进模型的那份像素"。

用法:
    python verify_model_input_same_source.py [--svc http://127.0.0.1:8791] [--box http://<host>:<port>]

判据: 取回图的像素 md5 == 台账(如 /last_result).model_input_md5, 且与 meta 一致。
在线系统一直在动 ⇒ **按帧号对齐**才下结论; 对不齐就如实报"未对齐"(退出码 2)。
⚠️ 跑之前先确认两边 n 是同一个计数器(台账 n 可能是"检测序号"而不是"帧号")。
"""
import argparse
import hashlib
import json
import time
import urllib.request

import cv2
import numpy as np


def _json(url, timeout=15):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8", "ignore"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8", "ignore") or "{}")
        except Exception:                                                       # noqa: BLE001
            return e.code, {}
    except Exception as e:                                                      # noqa: BLE001
        return 0, {"_err": str(e)[:80]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--svc", default="http://127.0.0.1:8791", help="带 /aoi_modelin.png 转发路由的服务")
    ap.add_argument("--box", default="http://192.168.23.23:10082", help="组件本体")
    ap.add_argument("--tries", type=int, default=14)
    a = ap.parse_args()

    for _ in range(a.tries):
        try:
            with urllib.request.urlopen(a.svc + "/aoi_modelin.png", timeout=20) as r:
                body, hd = r.read(), dict(r.headers)
        except Exception as e:                                                  # noqa: BLE001
            print("取图异常: %s" % str(e)[:90])
            time.sleep(1)
            continue
        n_img = hd.get("X-Zmax-Modelin-N")
        _st, lr = _json(a.box + "/last_result")
        _st2, mi = _json(a.box + "/picture?kind=modelin&meta=1")
        if str(lr.get("n")) != str(n_img) or str(mi.get("n")) != str(n_img):
            time.sleep(0.3)
            continue                                    # 又拍了一张/语义不同 ⇒ 重来
        img = cv2.imdecode(np.frombuffer(body, np.uint8), cv2.IMREAD_COLOR)
        md5 = hashlib.md5(np.ascontiguousarray(img).tobytes()).hexdigest()
        print("帧 n=%s  %dx%d  取回图 md5=%s" % (n_img, img.shape[1], img.shape[0], md5))
        print("  台账 model_input_md5 = %s  ⇒ 逐位同源: %s" % (lr.get("model_input_md5"), md5 == lr.get("model_input_md5")))
        print("  meta  md5            = %s  ⇒ 同一份: %s" % (mi.get("md5"), md5 == mi.get("md5")))
        print("  模型吃: %s  |  给人看: %s" % (lr.get("model_input"), lr.get("judge")))
        print("  返回值: %s" % json.dumps({"count": lr.get("count"), "verdict": lr.get("verdict"),
                                          "ms": lr.get("ms"), "defects": lr.get("defects")}, ensure_ascii=False))
        return 0 if md5 == lr.get("model_input_md5") == mi.get("md5") else 1
    print("⚠️ %d 次都没对齐到同一帧 —— 不作结论(先确认两边 n 是同一个计数器, 或改用受控的一次真检测取帧)" % a.tries)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

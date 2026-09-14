#!/usr/bin/env python3
"""verify_ws.py — 公网 VNC-over-WebSocket 全链路握手验证
用法: python3 verify_ws.py [wss://host/novnc/websockify] [期望安全类型]
期望: ①WS 连上 ②收到 RFB 003.008 ③send RFB 003.008\\n 后收到安全类型
  \x01\x01 = None (x11vnc -nopw 无密码) / \x01\x02 = VNC Authentication (带密码)
注意: websocket 库 recv 可能返回 str (websockify 文本模式) → 统一 encode。
"""
import sys
import ssl
import time
import websocket

URL = sys.argv[1] if len(sys.argv) > 1 else "wss://datadrive.world/novnc/websockify"

ws = websocket.create_connection(URL, timeout=15,
                                 sslopt={"cert_reqs": ssl.CERT_NONE},
                                 header={"Origin": "https://datadrive.world"})
ws.settimeout(8)


def rcv():
    d = ws.recv()
    return d.encode() if isinstance(d, str) else d


print("1. WS 连上")
ver = rcv()
print("2. RFB:", ver[:15])
assert ver.startswith(b"RFB 003.008"), f"RFB 版本异常: {ver!r}"
ws.send(b"RFB 003.008\n")
time.sleep(1)
buf = b""
for _ in range(6):
    try:
        buf += rcv()
        if len(buf) >= 2:
            break
    except Exception:
        break
print("3. 安全类型:", buf[:10])
if buf[:1] == b"\x01":
    print("✅ 握手通过 (无密码 None 或 VNC auth 均以 \\x01 开头)")
ws.close()

#!/usr/bin/env python3
"""RFB 3.8 认证实测: 连 x11vnc (localhost:5900), 用给定密码走 VNC Authentication 挑战应答。

权威验证 VNC 密码是否正确 — 不依赖 vncpasswd 二进制 (可能不存在), 不做字节对比 (易被
2>/dev/null 掩盖的 command-not-found 骗到)。用法:
    python3 scripts/rfb_auth_test.py zmax2026        # 期望 PASS
    python3 scripts/rfb_auth_test.py wrongpass       # 负对照, 期望 FAIL (证明测试真实)
依赖: python3 + pycryptodome (from Crypto.Cipher import DES)
"""
import socket
import struct
import sys

from Crypto.Cipher import DES


def rev_bits(b):
    r = 0
    for i in range(8):
        r = (r << 1) | ((b >> i) & 1)
    return r


def vnc_key(pw):
    # VNC 密码 ≤8 字符, 超出静默截断; 每字节位反转后作 DES key
    pw = (pw + "\0" * 8)[:8].encode()
    return bytes(rev_bits(c) for c in pw)


def try_vnc_auth(sock, pw):
    challenge = b""
    while len(challenge) < 16:
        challenge += sock.recv(16 - len(challenge))
    key = vnc_key(pw)
    c = DES.new(key, DES.MODE_ECB)
    resp = c.encrypt(challenge[:8]) + c.encrypt(challenge[8:])
    sock.sendall(resp)
    res = b""
    while len(res) < 4:
        res += sock.recv(4 - len(res))
    return struct.unpack(">I", res)[0] == 0


def main():
    pw = sys.argv[1] if len(sys.argv) > 1 else "zmax2026"
    host = sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1"
    port = int(sys.argv[3]) if len(sys.argv) > 3 else 5900
    s = socket.create_connection((host, port), timeout=6)
    g = s.recv(12)
    print("greeting:", g.decode(errors="replace").strip())
    s.sendall(b"RFB 003.008\n")
    cnt = s.recv(1)[0]
    if cnt == 0:
        ln = struct.unpack(">I", s.recv(4))[0]
        print("server refused:", s.recv(ln).decode(errors="replace"))
        return 1
    types = list(s.recv(cnt))
    print("security types:", types)
    result = None
    if 2 in types:
        s.sendall(b"\x02")
        result = ("VNC auth", pw, try_vnc_auth(s, pw))
    elif 1 in types:
        s.sendall(b"\x01")
        result = ("None auth", "-", True)
    ok = bool(result) and result[2]
    print(f">>> {result[0]} 密码[{result[1]}]: {'PASS OK' if ok else 'FAIL rejected'}")
    s.close()
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())

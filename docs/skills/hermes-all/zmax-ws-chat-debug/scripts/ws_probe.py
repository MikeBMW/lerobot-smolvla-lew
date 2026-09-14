#!/usr/bin/env python3
"""WS 探测脚本: 发 hello 看服务端回什么 (群聊/推送诊断)
用法: python3 ws_probe.py [ws://host/ws]
返回: 服务端首帧 (orin_status=无群聊 / history=群聊正常)
"""
import socket, base64, os, struct, time, json, sys

URL = sys.argv[1] if len(sys.argv) > 1 else "ws://datadrive.world/ws"
# 解析 ws://host[:port]/path
rest = URL.replace("ws://", "").replace("wss://", "")
host = rest.split("/")[0].split(":")[0]
port = 80 if "wss://" not in URL and ":" not in rest.split("/")[0] else (443 if "wss://" in URL else int(rest.split("/")[0].split(":")[1]))
path = "/" + rest.split("/", 1)[1] if "/" in rest else "/"

def ws_handshake():
    s = socket.create_connection((host, port), timeout=8)
    key = base64.b64encode(os.urandom(16)).decode()
    req = (f'GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\n'
           'Upgrade: websocket\r\nConnection: Upgrade\r\n'
           f'Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n')
    s.sendall(req.encode())
    resp = s.recv(4096).decode(errors='ignore')
    return s, resp

def ws_send(s, payload):
    data = payload.encode()
    mask = os.urandom(4)
    if len(data) < 126:
        header = bytes([0x81, 0x80 | len(data)])
    else:
        header = bytes([0x81, 0x80 | 126]) + struct.pack('>H', len(data))
    s.sendall(header + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

def ws_recv(s, timeout=5):
    s.settimeout(timeout)
    try:
        data = s.recv(4096)
        if not data:
            return None
        b1, b2 = data[0], data[1]
        opcode = b1 & 0x0f
        ln = b2 & 0x7f
        off = 2
        if ln == 126:
            ln = struct.unpack('>H', data[2:4])[0]; off = 4
        elif ln == 127:
            ln = struct.unpack('>Q', data[2:10])[0]; off = 10
        return opcode, data[off:off+ln].decode(errors='ignore')
    except socket.timeout:
        return 'timeout'

s, resp = ws_handshake()
print('握手:', resp.split('\r\n')[0])
ws_send(s, json.dumps({"type": "hello", "from": "probe"}))
print('已发 hello')
for i in range(3):
    r = ws_recv(s, 4)
    if r == 'timeout':
        print(f'[{i}] 4s 超时')
    elif r is None:
        print(f'[{i}] 连接关闭')
    else:
        opcode, payload = r
        print(f'[{i}] opcode={opcode}: {payload[:300]}')
        if opcode == 8:
            break
s.close()

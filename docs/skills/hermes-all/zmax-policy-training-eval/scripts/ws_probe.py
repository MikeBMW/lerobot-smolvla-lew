#!/usr/bin/env python3
"""WS 服务端行为探针 — 诊断"网页/群聊/实时通道没消息"根因 (2026-08-10)
用法: python ws_probe.py [host] [path]   # 默认 datadrive.world /ws
三步诊断:
  1. 握手 (101 = WS 服务在线)
  2. 发 hello (必须带掩码, 否则服务端回关闭帧 "incorrect masking")
  3. 收帧解析 opcode (1=文本消息, 8=关闭) → 看服务端推什么类型
判定: 握手通但只回 orin_status/status 类 = 服务端没实现你要的消息类型 (群聊/历史),
      不是连接问题。ws:// 通而 wss:// 426 = nginx 没配 SSL WS 转发。
"""
import base64
import json
import os
import socket
import struct
import sys


def ws_handshake(host='datadrive.world', path='/ws', port=80):
    s = socket.create_connection((host, port), timeout=8)
    key = base64.b64encode(os.urandom(16)).decode()
    req = (f'GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\n'
           'Upgrade: websocket\r\nConnection: Upgrade\r\n'
           f'Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n')
    s.sendall(req.encode())
    resp = s.recv(4096).decode(errors='ignore')
    return s, resp


def ws_send(s, payload):
    """客户端→服务端帧必须掩码 (0x80 | len)"""
    data = payload.encode()
    mask = os.urandom(4)
    if len(data) < 126:
        header = bytes([0x81, 0x80 | len(data)])
    else:
        header = bytes([0x81, 0x80 | 126]) + struct.pack('>H', len(data))
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    s.sendall(header + mask + masked)


def ws_recv(s, timeout=5):
    """服务端→客户端帧无掩码; 返回 (opcode, payload_bytes) 或 'timeout'"""
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
            ln = struct.unpack('>H', data[2:4])[0]
            off = 4
        elif ln == 127:
            ln = struct.unpack('>Q', data[2:10])[0]
            off = 10
        return opcode, data[off:off + ln]
    except socket.timeout:
        return 'timeout'


def main():
    host = sys.argv[1] if len(sys.argv) > 1 else 'datadrive.world'
    path = sys.argv[2] if len(sys.argv) > 2 else '/ws'
    s, resp = ws_handshake(host, path)
    print('握手:', resp.split('\r\n')[0])
    if '101' not in resp.split('\r\n')[0]:
        print('⚠️ 非 101 — 通道不通 (看 HTTP 状态: 426=SSL 转发未配, 404=路径错)')
        return
    # 发 hello (模拟浏览器 onopen)
    ws_send(s, json.dumps({'type': 'hello', 'from': 'probe'}))
    print('已发 hello, 等服务端回消息...')
    for i in range(3):
        r = ws_recv(s, 4)
        if r == 'timeout':
            print(f'[{i}] 4s 超时 (服务端不主动推)')
        elif r is None:
            print(f'[{i}] 连接关闭')
        else:
            opcode, payload = r
            txt = payload.decode(errors='ignore')
            print(f'[{i}] opcode={opcode} (1=文本/8=关闭): {txt[:300]}')
    s.close()


if __name__ == '__main__':
    main()

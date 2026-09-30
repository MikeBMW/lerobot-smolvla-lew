#!/usr/bin/env python3
"""产线/工业局域网 设备清点 (ARP 层枚举 + 身份识别) — 2026-09-18 实测可用

用法:
    python3 lan_inventory.py <本机网卡> [网段前缀]
例:
    python3 lan_inventory.py enx00e04c0c32a0 192.168.23.

做了什么 (顺序即信息量):
  ① ip neigh flush → 对 1-254 逐个 UDP sendto((ip,9)) 触发 ARP → 读 ip neigh 得真设备+MAC (不需 root)
  ② MAC OUI → 厂商 (api.macvendors.com, 串行+限速)
  ③ ping -c1 读 TTL 指纹 (Linux≈64 / Windows≈128 / 设备≈255)
  ④ 常见端口 + SSH/HTTP banner
  ⑤ Windows: NetBIOS NBSTAT (UDP 137) → 机器名/工作组
  ⑥ GigE Vision: GVCP 发现包 (UDP 3956) → 有没有相机/视觉设备 (它们常常没有任何 TCP 端口)
只读探测, 不写不改。
"""
import concurrent.futures as cf
import random
import re
import socket
import struct
import subprocess
import sys
import time
import urllib.request

IFACE = sys.argv[1] if len(sys.argv) > 1 else "enx00e04c0c32a0"
NET = sys.argv[2] if len(sys.argv) > 2 else "192.168.23."
COMMON = [22, 23, 80, 111, 135, 139, 443, 445, 502, 3389, 3956, 4840, 5900, 5985,
          8000, 8080, 8443, 8765, 9090, 3000, 5000, 9100, 10000, 10081]
NBSTAT_SUF = {0x00: "<00>工作站", 0x20: "<20>文件服务", 0x03: "<03>信使"}


def sh(*a):
    return subprocess.run(list(a), capture_output=True, text=True, timeout=60).stdout


def arp_sweep():
    """ARP 层枚举: 有 lladdr 的才是真设备"""
    subprocess.run(["ip", "neigh", "flush", "all", "dev", IFACE], capture_output=True)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for i in range(1, 255):
        try:
            s.sendto(b"x", (NET + str(i), 9))
        except Exception:
            pass
    s.close()
    time.sleep(2.5)
    live, dead = {}, []
    for ln in sh("ip", "neigh", "show", "dev", IFACE).splitlines():
        m = re.match(r"(\d+\.\d+\.\d+\.\d+) .*?(?:lladdr ([\da-f:]+))? ?(REACHABLE|STALE|DELAY|PROBE|FAILED|INCOMPLETE)", ln)
        if not m:
            continue
        ip, mac, st = m.group(1), m.group(2), m.group(3)
        if mac and st != "FAILED":
            live[ip] = mac
        elif st in ("FAILED", "INCOMPLETE"):
            dead.append(ip)
    return live, dead


def vendor(mac):
    """MAC OUI → 厂商。必须串行+间隔, 否则被限流成 '?'"""
    for _ in range(3):
        try:
            v = urllib.request.urlopen(f"https://api.macvendors.com/{mac}", timeout=10).read().decode()
            time.sleep(1.1)
            return v
        except Exception:
            time.sleep(2.5)
    return "?"


def ttl(ip):
    o = sh("ping", "-c", "1", "-W", "1", ip)
    m = re.search(r"ttl=(\d+)", o, re.I)
    return m.group(1) if m else "无应答"


def ports(ip):
    out = []
    def one(p):
        s = socket.socket(); s.settimeout(0.6)
        try:
            s.connect((ip, p)); return p
        except Exception:
            return None
        finally:
            s.close()
    with cf.ThreadPoolExecutor(max_workers=24) as ex:
        for r in ex.map(one, COMMON):
            if r:
                out.append(r)
    return sorted(out)


def banner(ip, ops):
    for p in ops:
        try:
            s = socket.socket(); s.settimeout(1.5); s.connect((ip, p))
            if p == 22:
                b = s.recv(120).decode("utf-8", "ignore").strip()
            elif p in (80, 8080, 8000, 8765, 9090, 5000, 3000, 10081):
                s.sendall(b"GET / HTTP/1.0\r\nHost: %s\r\n\r\n" % ip.encode())
                b = s.recv(200).decode("utf-8", "ignore").splitlines()[0]
            else:
                s.close(); continue
            s.close()
            return f":{p} {b[:80]}"
        except Exception:
            pass
    return ""


def nbstat(ip, timeout=3):
    """Windows 机器名 (UDP 137)。注意应答 qdcount 可能为 0 → 不按固定偏移, 直接扫 18B 名字记录"""
    tid = random.randrange(1, 0xFFFF)
    pkt = struct.pack(">HHHHHH", tid, 0, 1, 0, 0, 0)
    q = b"\x20" + b"CKAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" + b"\x00" + struct.pack(">HH", 0x0021, 0x0001)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(timeout)
    try:
        s.sendto(pkt + q, (ip, 137))
        d, _ = s.recvfrom(2048)
    except Exception:
        return None
    finally:
        s.close()
    found = set()
    for i in range(len(d) - 18):
        nm = d[i:i + 15].decode("ascii", "ignore").strip()
        suf, fl = d[i + 15], struct.unpack(">H", d[i + 16:i + 18])[0]
        if re.fullmatch(r"[A-Za-z0-9_\-]{3,15}", nm) and fl < 0x8000 and suf in NBSTAT_SUF and not nm.startswith("CK"):
            found.add(f"{nm} {NBSTAT_SUF[suf]}")
    return found or None


def gvcp(ip, timeout=2):
    """GigE Vision 发现 (UDP 3956) → 工业相机/视觉设备常常没有任何 TCP 端口"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(timeout)
    try:
        s.sendto(bytes([0x42, 0x11, 0x00, 0x02, 0x00, 0x00, 0x00, 0x01]), (ip, 3956))
        d, _ = s.recvfrom(600)
        return f"GVCP 应答 {len(d)}B"
    except Exception:
        return None
    finally:
        s.close()


def main():
    live, dead = arp_sweep()
    print(f"=== ARP 有应答(真设备) {len(live)} 台 · 空地址 {len(dead)} 个")
    for ip in sorted(live, key=lambda x: int(x.split(".")[-1])):
        mac = live[ip]
        ops = ports(ip)
        print(f"\n--- {ip}  {mac}")
        print(f"    厂商      : {vendor(mac)}")
        print(f"    TTL       : {ttl(ip)}")
        print(f"    开放端口  : {ops or '-'}")
        bn = banner(ip, ops)
        if bn:
            print(f"    banner    : {bn}")
        if any(p in ops for p in (135, 139, 445)):
            print(f"    NetBIOS   : {nbstat(ip) or '无应答'}")
        g = gvcp(ip)
        if g:
            print(f"    GigE Vision: {g}")


if __name__ == "__main__":
    main()

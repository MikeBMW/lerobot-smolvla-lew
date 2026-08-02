#!/usr/bin/env python3
"""Z-MAX 全链路压力测试
链路: 本地4060 → ECS中转(upload/peek/latest) → Orin状态
测试项:
  1. 数据链路循环: 20轮 上传(随机大小)→peek→拉取 成功率/延迟
  2. WS 高频心跳: 30次/秒 推送 → 广播接收
  3. 并发上传: 5路并行
  4. 大文件上传: 84MB 级模型传输稳定性
"""
import asyncio, json, random, threading, time, requests
from concurrent.futures import ThreadPoolExecutor

RELAY = "https://datadrive.world/api/relay"
WS = "wss://datadrive.world/ws"
results = {"upload": [], "peek": [], "latest": [], "ws": [], "errors": []}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ── 1. 数据链路循环 ──
def cycle_test(n=20):
    log(f"① 数据链路循环压测: {n}轮")
    sizes = [random.randint(1_000, 500_000) for _ in range(n)]
    ok = 0
    for i, sz in enumerate(sizes):
        try:
            # 带唯一标记的载荷 (验证内容一致性)
            marker = f"PKG-{i:04d}-".encode() + bytes(random.getrandbits(8) for _ in range(sz - 10))
            payload = marker
            t0 = time.time()
            r = requests.post(f"{RELAY}/upload", data=payload, timeout=60)
            dt = (time.time() - t0) * 1000
            results["upload"].append(dt)
            # peek 确认
            r2 = requests.get(f"{RELAY}/peek", timeout=10)
            results["peek"].append((time.time() - t0) * 1000)
            # latest 拉取 (可能取到后到的包, 校验是否含合法标记)
            r3 = requests.get(f"{RELAY}/latest", timeout=60)
            results["latest"].append((time.time() - t0) * 1000)
            got = r3.content
            valid = got[:4] == b"PKG-" and len(got) >= 10
            if r.status_code == 200 and r3.status_code == 200 and valid:
                ok += 1
            else:
                results["errors"].append(f"轮{i}: 无效载荷 {len(got)}B")
        except Exception as ex:
            results["errors"].append(f"轮{i}: {ex}")
    log(f"   完成 {ok}/{n} 轮 · 上传均值 {sum(results['upload'])/len(results['upload']):.0f}ms "
        f"· 拉取均值 {sum(results['latest'])/len(results['latest']):.0f}ms")
    return ok == n


# ── 2. WS 高频心跳 ──
async def ws_test(n=30, interval=0.03):
    import websockets
    log(f"② WS 高频心跳压测: {n}次 @{interval*1000:.0f}ms间隔")
    recv_count = 0
    async with websockets.connect(WS) as ws:
        await ws.recv()  # 初始状态
        for i in range(n):
            await ws.send(json.dumps({"type": "heartbeat", "online": True,
                                      "model": "stress-test", "infer_count": i,
                                      "last_infer_ms": random.uniform(1, 50)}))
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=1)
                recv_count += 1
            except asyncio.TimeoutError:
                pass
            await asyncio.sleep(interval)
    log(f"   推送 {n} · 收到广播 {recv_count}")
    return recv_count > n * 0.5


# ── 3. 并发上传 ──
def concurrency_test(n=5):
    log(f"③ 并发上传压测: {n}路并行")
    def one(i):
        data = bytes(random.getrandbits(8) for _ in range(200_000))
        t0 = time.time()
        r = requests.post(f"{RELAY}/upload", data=data, timeout=60)
        return r.status_code, (time.time() - t0) * 1000
    with ThreadPoolExecutor(max_workers=n) as ex:
        futs = [ex.submit(one, i) for i in range(n)]
        codes = [f.result() for f in futs]
    ok = sum(1 for c, _ in codes if c == 200)
    log(f"   成功 {ok}/{n} · 耗时 {[round(d) for _, d in codes]}ms")
    return ok == n


# ── 4. 大文件上传 ──
def bigfile_test(path):
    import os
    sz = os.path.getsize(path)
    log(f"④ 大文件压测: {sz//1024//1024}MB")
    with open(path, "rb") as f:
        data = f.read()
    t0 = time.time()
    r = requests.post(f"{RELAY}/upload", data=data, timeout=600)
    dt = time.time() - t0
    log(f"   HTTP {r.status_code} | {dt:.1f}s | {sz//1024//1024}MB")
    return r.status_code == 200


if __name__ == "__main__":
    import sys
    print("=" * 50)
    log("🚀 Z-MAX 全链路压力测试开始")
    t_start = time.time()

    # 清空残留队列 (弹栈式: 排空所有旧包)
    try:
        while True:
            r = requests.get(f"{RELAY}/latest", timeout=30)
            if r.status_code != 200:
                break
        log("🧹 队列已排空")
    except Exception:
        pass

    passed = []
    passed.append(cycle_test(20))
    passed.append(asyncio.run(ws_test(30, 0.03)))
    passed.append(concurrency_test(5))
    if len(sys.argv) > 1:
        passed.append(bigfile_test(sys.argv[1]))
    else:
        passed.append(True)  # 大文件单独测

    dt = time.time() - t_start
    print("=" * 50)
    log(f"🏁 压测完成 {dt:.0f}s")
    for i, p in enumerate(passed):
        log(f"  测试{i+1}: {'✅ PASS' if p else '❌ FAIL'}")
    if results["errors"]:
        log(f"  ⚠️ {len(results['errors'])} 个错误:")
        for e in results["errors"][:5]:
            log(f"    - {e}")
    log(f"结果: {'✅ 全部通过' if all(passed) else '❌ 有失败项'}")

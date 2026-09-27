#!/usr/bin/env python3
"""公网穿透用**安全闸门代理** —— 只放行只读 GET 到 8791, 其余一律挡掉。

为什么必须有它(2026-09-27):
  8791 上带着`手动控制真机`的接口。虽然服务自己已做对了两件事
  (① 只有 POST 能触发动作, GET 不行 ② 真动还需 5 分钟授权), 但一旦把 8791
  整条露到公网, 任何拿到链接的人都能试 POST。/ctl/move -> 机器人会真的动。
  所以穿透**只指向本代理**, 代理只转发白名单里的 GET:
    · 视频/页面/快照/场景契约/stats/APK 下载  -> 放行
    · 一切 POST/PUT/DELETE, 以及 /ctl/*、/station、/gen(会真拍照)  -> 403
  再叠一层: 可选用共享口令 k=<token>(带 ?k= 打开就种 cookie, 之后同源请求自动带)。

用法:
  python3 tools/tunnel_proxy.py --port 8891 --token zmax-live --upstream 127.0.0.1:8791
  # 然后: ssh -R 80:localhost:8891 nokey@localhost.run
"""
import argparse
import http.client
import http.server
import io
import json
import re
import socketserver
import threading
import time

try:                                                                          # 拼图流要用
    from PIL import Image
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False

# 拼图流: 默认三相机横排, 每格 400px 宽, 质量 60, 2fps
# (隧道实测 ~66KB/s ⇒ 原始流 45KB/帧 ×10fps 跑不动; 拼图 ~28KB/帧 ×2fps ≈ 56KB/s 刚好过得去)
WALL_CAMS = [("arm", "臂 D405"), ("local", "笔记本"), ("local2", "MAXHUB")]
WALL = {"fps": 2.0, "w": 400, "q": 60, "layout": "h", "last": 0.0, "cache": b"", "err": ""}

# 只读白名单(正则, 全匹配) —— 想加路径必须显式加在这里
ALLOW = [
    r"/", r"/index\.html",
    r"/overlay", r"/overlay/[A-Za-z0-9_.]+",
    r"/app", r"/app\.html",
    r"/scene\.json", r"/stats", r"/robot_status", r"/motion",
    r"/ctl/status",
    r"/snapshot/[A-Za-z0-9_]+\.jpg",
    r"/[A-Za-z0-9_]+\.mjpg",
    r"/wall[A-Za-z0-9_]*\.jpg", r"/wall\.mjpg", r"/live\.json",
    r"/live", r"/live\.html",
    r"/dl/[A-Za-z0-9_.-]+",
    r"/lib/[A-Za-z0-9_./-]+",
]
ALLOW_RE = [re.compile("^" + p + "$") for p in ALLOW]
# 明确点名拒绝(即便将来白名单放宽, 这些也永不外放)
# 注意: /ctl/status 与 /motion 是只读状态, 故意**不在**这里(它们在白名单里)
DENY = [r"/ctl/(arm|move)", r"/api/ctl/(arm|move)", r"/station.*", r"/gen.*", r"/tap.*",
        r"/move.*", r"/api/relay/.*", r"/api/ctl/.*"]
DENY_RE = [re.compile("^" + p + "$") for p in DENY]

STATE = {"token": "", "blocked": 0, "served": 0, "up": ("127.0.0.1", 8791)}


def _up(path, timeout=6):
    """取一次上游(8791)的只读资源, 失败返回 None。"""
    try:
        c = http.client.HTTPConnection(STATE["up"][0], STATE["up"][1], timeout=timeout)
        c.request("GET", path, headers={"Host": "127.0.0.1"})
        r = c.getresponse()
        d = r.read()
        c.close()
        return d if r.status == 200 else None
    except Exception:                                                         # noqa: BLE001
        return None


def _stats():
    d = _up("/stats", timeout=4)
    if not d:
        return {}
    try:
        return json.loads(d)
    except Exception:                                                         # noqa: BLE001
        return {}


def _tile(im, w, label):
    """统一格子大小(4:3 信箱) + 底部贴一行"路名 · 拍照时刻 · 帧龄" —— 画面自己要说清是什么。"""
    th = int(w * 0.75)
    box = Image.new("RGB", (w, th), (12, 12, 12))
    if im is not None:
        sc = min(w / im.width, th / im.height)
        r = im.resize((max(1, int(im.width * sc)), max(1, int(im.height * sc))),
                      getattr(Image, "Resampling", Image).BILINEAR)
        box.paste(r, ((w - r.width) // 2, (th - r.height) // 2))
    strip = Image.new("RGB", (w, 16), (0, 0, 0))
    box.paste(strip, (0, th - 16))
    try:
        from PIL import ImageDraw
        ImageDraw.Draw(box).text((4, th - 14), label[:46], fill=(255, 235, 120))
    except Exception:                                                         # noqa: BLE001
        pass
    return box


def build_wall(w=400, q=60, layout="h"):
    """抓三路叠加快照拼一张图。返回 (jpeg_bytes, 说明)。

    三路快照**并发取**(实测串行每帧 1.2s ⇒ 只有 0.8fps; 并发后应回到 2fps)。
    """
    if not HAVE_PIL:
        return None, "服务端缺 PIL"
    st = _stats().get("sources", {})

    def grab(key):
        d = _up("/snapshot/overlay_%s.jpg" % key) or _up("/snapshot/%s.jpg" % key)
        if not d:
            return key, None
        try:
            return key, Image.open(io.BytesIO(d)).convert("RGB")
        except Exception:                                                     # noqa: BLE001
            return key, None

    imgs = {}
    try:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=len(WALL_CAMS)) as ex:
            for key, im in ex.map(grab, [k for k, _ in WALL_CAMS]):
                imgs[key] = im
    except Exception:                                                         # noqa: BLE001
        for key, _n in WALL_CAMS:                                             # 兜底: 退回串行
            _k, im = grab(key)
            imgs[key] = im

    tiles = []
    for key, name in WALL_CAMS:
        im = imgs.get(key)
        s = st.get(key) or st.get("ov_" + key) or {}
        age = s.get("age")
        fps = s.get("fps")
        tag = "%s · %s" % (name, time.strftime("%H:%M:%S"))
        if isinstance(age, (int, float)):
            tag += " · 帧龄%.1fs" % age
        if isinstance(fps, (int, float)):
            tag += " · %.0ffps" % fps
        if im is None:
            tag += " · ✗取不到"
        tiles.append(_tile(im, w, tag))
    if all(t is None for t in tiles):
        return None, "三路都取不到"
    if layout == "v":
        out = Image.new("RGB", (w, tiles[0].height * len(tiles)), (0, 0, 0))
        for i, t in enumerate(tiles):
            out.paste(t, (0, i * t.height))
    else:
        out = Image.new("RGB", (w * len(tiles), tiles[0].height), (0, 0, 0))
        for i, t in enumerate(tiles):
            out.paste(t, (i * t.width, 0))
    buf = io.BytesIO()
    out.save(buf, "JPEG", quality=q, optimize=True)
    return buf.getvalue(), "%dx%d q%d" % (out.width, out.height, q)


def live_manifest(token):
    """给 web 照单接线的清单: 每个源是什么、码率多大、口令怎么带。"""
    st = _stats()
    return {
        "ok": True,
        "who": "4060 工位机(视频源推流端)",
        "token": token,
        "note": "本机在 146.x 私网段, 外网不可直达 ⇒ 需 web 侧端口转发(frp/nginx)或直接用隧道地址",
        "streams": {
            "三相机拼图(推荐, 低码率)": {
                "mjpg": "/wall.mjpg?k=%s" % token,
                "single_frame": "/wall.jpg?k=%s" % token,
                "params": "w=400(每格宽) q=60(画质) fps=2 layout=h|v",
                "bytes": "~28KB/帧, 2fps ≈ 56KB/s",
            },
            "单路原始": {k: "/%s.mjpg?k=%s" % (k, token) for k in ("arm", "overlay_arm", "local", "local2", "ov_local", "ov_local2")},
            "单张快照": {k: "/snapshot/%s.jpg?k=%s" % (k, token) for k in ("arm", "local", "local2", "overlay_arm", "overlay_local", "overlay_local2")},
            "场景契约(叠加框/位姿)": "/scene.json?k=%s" % token,
        },
        "cameras": {k: n for k, n in WALL_CAMS},
        "fps_now": {k: (st.get("sources", {}).get(k, {}) or {}).get("fps") for k, _ in WALL_CAMS},
        "禁止": "POST 一律 403; /ctl/*(真机动) /gen(触发拍照) /station /tap 永不外放",
    }



class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    upstream: tuple = ("127.0.0.1", 8791)
    timeout_s = 30

    def log_message(self, format, *args):          # noqa: A002  (签名须与基类一致)
        pass

    def _deny(self, code, msg):
        body = ("%s\n" % msg).encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        print("[proxy] %-15s %s %s -> %d %s" % (self.client_address[0], self.command,
                                                self.path[:60], code, msg), flush=True)

    def _bytes(self, code, data, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(data)
        except Exception:                                                     # noqa: BLE001
            pass
        STATE["served"] += 1

    def _token_ok(self) -> bool:
        """口令闸: 空口令=不校验; 否则 URL 带 ?k=<token> 或带 cookie zmaxk 才放行。"""
        if not STATE["token"]:
            return True
        if ("k=" + STATE["token"]) in (self.path or ""):
            return True
        return ("zmaxk=" + STATE["token"]) in (self.headers.get("Cookie") or "")

    def _want_cookie(self) -> bool:
        """这次请求是靠 URL 里的 ?k= 过闸的 ⇒ 回一个 cookie, 让页面内同源子请求自动带上。"""
        return bool(STATE["token"]) and ("k=" + STATE["token"]) in (self.path or "")

    def do_POST(self):
        STATE["blocked"] += 1
        self._deny(403, "403: 公网通道只读 —— POST 一律拒绝(防止有人用它动机器人)")

    do_PUT = do_DELETE = do_PATCH = do_POST

    def do_HEAD(self):
        self._deny(405, "405: HEAD 未开放(用 GET)")

    def do_GET(self):
        path = (self.path or "/").split("?")[0]
        if not self._token_ok():
            STATE["blocked"] += 1
            self._deny(403, "403: 需要口令 —— 用带 ?k=<token> 的链接打开一次即可")
            return
        for r in DENY_RE:
            if r.match(path):
                STATE["blocked"] += 1
                self._deny(403, "403: 该路径不对外(控制类/触发类)")
                return
        if not any(r.match(path) for r in ALLOW_RE):
            STATE["blocked"] += 1
            self._deny(403, "403: 不在只读白名单内")
            return

        # ── 本地合成: 三相机拼图流 / 清单(web 照单接线用) ──────────────────
        # ── 窄带直播页: APP 就该载它(而不是 287KB/轮的叠加页) ──────────────
        if path in ("/live", "/live.html"):
            token = STATE["token"]
            page = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Z-MAX 实况</title><style>
html,body{margin:0;height:100%;background:#000;color:#ddd;overflow:hidden;
  font:13px/1.5 system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
#bar{position:fixed;inset:0 0 auto 0;height:28px;display:flex;align-items:center;gap:10px;
  padding:0 10px;background:#0d0d0de6;font-size:12.5px;z-index:9}
#dot{width:8px;height:8px;border-radius:50%;background:#e33}
#dot.on{background:#3d3}
#v{position:fixed;inset:28px 0 0 0;width:100%;height:calc(100% - 28px);object-fit:contain;background:#000}
#hint{position:fixed;inset:auto 0 0 0;padding:6px 10px;background:#0d0d0de6;font-size:11.5px;color:#aaa}
</style></head><body>
<div id="bar"><span id="dot"></span><span id="st">连接中…</span>
<span style="margin-left:auto" id="clk"></span></div>
<img id="v" alt="现场三相机">
<div id="hint">三相机拼图(臂 D405 / 笔记本 / MAXHUB) · 画面自带拍照时刻与帧龄 · 点住可刷新</div>
<script>
var n=0,img=document.getElementById('v'),st=document.getElementById('st'),
    dot=document.getElementById('dot'),clk=document.getElementById('clk');
function clock(){clk.textContent=new Date().toLocaleTimeString('zh-CN',{hour12:false});}
setInterval(clock,1000);clock();
function play(){
  n++;
  var q=location.search||('?k=__TOKEN__');
  img.src='/wall.mjpg'+q+(q.indexOf('?')>=0?'&':'?')+
          'w=320&q=48&fps=2&layout=v&_='+Date.now();
  st.textContent=n===1?'拉流中…':('重连中…(第'+n+'次)');
}
img.onload=function(){dot.className='on';st.textContent='直播中 · 2fps';};
img.onerror=function(){dot.className='';st.textContent='断线, 2 秒后重连';setTimeout(play,2000);};
img.onclick=function(){play();};
play();
</script></body></html>""".replace("__TOKEN__", token)
            self._bytes(200, page.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/live.json":
            self._bytes(200, json.dumps(live_manifest(STATE["token"]), ensure_ascii=False,
                                        indent=1).encode(), "application/json; charset=utf-8")
            return
        if path in ("/wall.jpg", "/wall.mjpg"):
            qs = {}
            if "?" in (self.path or ""):
                for kv in self.path.split("?", 1)[1].split("&"):
                    if "=" in kv:
                        qs[kv.split("=", 1)[0]] = kv.split("=", 1)[1]

            def num(k, d, lo, hi):
                try:
                    return max(lo, min(hi, float(qs.get(k, d))))
                except Exception:                                             # noqa: BLE001
                    return d
            w = int(num("w", 400, 160, 1280))
            q = int(num("q", 60, 30, 92))
            fps = num("fps", WALL["fps"], 0.5, 12)
            layout = "v" if qs.get("layout") == "v" else "h"
            if path == "/wall.jpg":
                jpg, info = build_wall(w, q, layout)
                if jpg is None:
                    self._deny(503, "503: 拼图取不到 (%s)" % info)
                else:
                    self._bytes(200, jpg, "image/jpeg")
                return
            # 拼图流: 无限 multipart, 按 fps 节流
            bnd = "zmaxwall"
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=%s" % bnd)
            self.send_header("Connection", "close")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.close_connection = True
            t_end = time.time() + 3600.0                     # 单连接最长 1 小时, 由客户端重连
            n = 0
            while time.time() < t_end:
                t0 = time.time()
                jpg, info = build_wall(w, q, layout)
                if jpg:
                    try:
                        self.wfile.write(("--%s\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n"
                                          % (bnd, len(jpg))).encode() + jpg + b"\r\n")
                        self.wfile.flush()
                        n += 1
                        STATE["served"] += 1
                    except Exception:                                         # noqa: BLE001
                        break                                                 # 客户端走了
                dt = time.time() - t0
                time.sleep(max(0.0, 1.0 / fps - dt))
            print("[proxy] 拼图流结束: 本次推 %d 帧 (w=%d q=%d fps=%.1f %s)" % (n, w, q, fps, layout),
                  flush=True)
            return

        try:
            conn = http.client.HTTPConnection(self.upstream[0], self.upstream[1], timeout=self.timeout_s)
            conn.request("GET", self.path, headers={"Host": "127.0.0.1", "User-Agent": "tunnel-proxy"})
            resp = conn.getresponse()
        except Exception as e:                                                # noqa: BLE001
            self._deny(502, "502: 上游不可达 %s" % str(e)[:60])
            return
        self.send_response(resp.status)
        is_stream = (resp.getheader("Content-Type") or "").startswith("multipart/")
        for k, v in resp.getheaders():
            if k.lower() in ("transfer-encoding", "connection", "content-length"):
                continue
            self.send_header(k, v)
        if self._want_cookie():          # 带 ?k= 进来 ⇒ 种 cookie, 页面内同源子请求自动过闸
            self.send_header("Set-Cookie", "zmaxk=%s; Path=/; Max-Age=86400; SameSite=Lax"
                             % STATE["token"])
        if is_stream:
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:                                                              # MJPEG 分块转发, 边收边发
                while True:
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except Exception:
                pass
            finally:
                conn.close()
        else:
            data = resp.read()
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(data)
            except Exception:
                pass
            conn.close()
        STATE["served"] += 1


class Srv(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8891)
    ap.add_argument("--bind", default="127.0.0.1")
    ap.add_argument("--upstream", default="127.0.0.1:8791")
    ap.add_argument("--token", default="", help="共享口令; 空=不校验(不建议对公网开放)")
    ap.add_argument("--wall-fps", type=float, default=2.0, help="三相机拼图流默认帧率")
    a = ap.parse_args()
    H.upstream = tuple(a.upstream.split(":"))
    H.upstream = (H.upstream[0], int(H.upstream[1]))
    STATE["up"] = H.upstream
    STATE["token"] = a.token
    WALL["fps"] = float(a.wall_fps)
    srv = Srv((a.bind, a.port), H)

    def beat():
        while True:
            time.sleep(60)
            print("[proxy] 60s: 放行 %d 次, 挡掉 %d 次" % (STATE["served"], STATE["blocked"]), flush=True)

    threading.Thread(target=beat, daemon=True).start()
    print("[proxy] 只读闸门: %s:%d -> %s  口令=%s" % (
        a.bind, a.port, a.upstream, "开" if a.token else "关(仅内网用)"), flush=True)
    print("[proxy] 放行: %s" % ", ".join(ALLOW), flush=True)
    print("[proxy] 永不放行: %s" % ", ".join(DENY), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()

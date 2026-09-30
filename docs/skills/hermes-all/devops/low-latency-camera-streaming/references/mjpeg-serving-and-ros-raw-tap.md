# 代码配方：MJPEG 服务 / MJPEG 解析录制 / ROS 全速原始帧抓取

三块可拼装的最小实现。工位机侧用有 cv2 的 venv（本环境 `gui-venv311/bin/python`，
实测 cv2 5.0.0 / numpy 2.4.6 / PIL 12.3.0，**无 flask** → 所以用 stdlib）。
本机实际实现（可直接参考/复用）：`tools/cam_live_stream.py` · `tools/record_mjpeg.py` · `tools/ros_arm_tap_raw.py`。

---

## ① MJPEG 服务骨架（stdlib，无依赖）

```python
import threading, time, json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import cv2

_LOCK = threading.Lock()
_FRAMES = {"arm": {"jpg": None, "ts": 0.0, "seq": 0, "src_ts": 0.0, "raw_kb": 0.0}}
_STOP = threading.Event()

# 多线程共享：B
# ── 关键：每个 GET 客户端一个线程，只等"新帧号" ──
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"          # 必需，否则 MJPEG 长连接被断

    def log_message(self, *a):              # 静音，否则每帧一行日志
        pass

    def _mjpeg(self, name):
        self.send_response(200)
        self.send_header("Content-Type",
                         "multipart/x-mixed-replace; boundary=zmaxframe")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        last_seq = -1
        while not _STOP.is_set():
            jpg, seq, ts, src_ts, _ = _get(name)
            if jpg is None or seq == last_seq:   # ← 只推新帧，旧帧丢弃(不积压)
                _STOP.wait(0.004)
                continue
            last_seq = seq
            try:
                self.wfile.write(b"--zmaxframe\r\n")
                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(jpg)}\r\n".encode())
                self.wfile.write(f"X-Frame-Age-S: {time.time()-src_ts:.3f}\r\n".encode())
                self.wfile.write(b"\r\n")
                self.wfile.write(jpg)          # 写完要补 \r\n 才分隔下一帧
                self.wfile.write(b"\r\n")
            except (BrokenPipeError, ConnectionResetError, OSError):
                break                          # 客户端关了, 退出该线程
```

要点：
- **必须 `protocol_version = "HTTP/1.1"`** + 自己写 `Content-Length`，否则每次请求后连接被关，流断。
- **`X-Frame-Age-S` 头**：让客户端/页面能直接显示帧龄，不必自己猜。
- **吞 `BrokenPipeError`**：手机切后台/刷新就会断连接，属正常，不能让服务崩。
- 页面里的 `<img src="/arm.mjpg">` 直接就能显示，浏览器原生支持 multipart/x-mixed-replace。
- 客户端侧不要 `cv2.VideoCapture(url)`（不可靠），要程序化拿帧就解析 multipart（见②）。

---

## ② MJPEG 解析 → 录 MP4（带标注，按实测帧率）

```python
BOUNDARY = b"--zmaxframe"

def frames_from_mjpeg(url, seconds):
    resp = urllib.request.urlopen(urllib.request.Request(url), timeout=15)
    buf, t0 = b"", time.time()
    while time.time() - t0 < seconds:
        chunk = resp.read(8192)
        if not chunk:
            break
        buf += chunk
        while True:
            i = buf.find(BOUNDARY)
            j = buf.find(b"\r\n\r\n", i) if i >= 0 else -1
            if j < 0:
                break
            head = buf[i:j].decode("latin-1", "replace")
            clen = None
            for line in head.split("\r\n"):        # ← 靠 Content-Length 切帧，别靠找 JPEG 魔术字
                if line.lower().startswith("content-length:"):
                    clen = int(line.split(":", 1)[1].strip())
            start = j + 4
            if clen is None or len(buf) < start + clen:
                break
            jpg, buf = buf[start:start + clen], buf[start + clen:]
            img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
            if img is not None:
                yield img, time.time()

# ── 写 mp4：帧率必须实测，否则播放速度失真 ──
fps = max(0.5, min((n - 1) / (ts[-1] - ts[0]), 60.0))   # n = 收到帧数
vw = cv2.VideoWriter(out, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))

# 交付前自检（【L目监会盯细节】界面自带状态）
g = cv2.cvtColor(imgs[len(imgs)//2], cv2.COLOR_BGR2GRAY)
assert g.std() > 5, f"疑似黑帧 std={g.std():.1f}"
```

标注（每帧叠一条黑底信息条）：
```python
bar = np.full((46, w, 3), 22, np.uint8)
im  = np.vstack([bar, im])
cv2.putText(im, f"{label}  {w}x{h}  {fps:.2f}fps", (8, 20), cv2.FONT_HERSHEY_SIMPLEX,
            0.55, (120, 255, 160), 1, cv2.LINE_AA)
cv2.putText(im, time.strftime("%H:%M:%S", time.localtime(t)) + f"  帧龄{t_end-t:.2f}s",
            (8, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (160, 160, 175), 1, cv2.LINE_AA)
```

发到聊天工具前转 H.264：
```bash
ffmpeg -y -i in.mp4 -c:v libx264 -preset veryfast -crf 24 \
  -pix_fmt yuv420p -movflags +faststart out.mp4
```

### 2.5 长录制（十几分钟以上）：落 raw `.mjpg`，最后一次性转码
边采边重编码很贵、把帧攒内存会吃掉几个 GB。长录制直接把 MJPEG 里的 JPEG 字节原样落盘：
```python
buf = b""
while time.time() - t0 < DUR:
    chunk = resp.read(65536)              # ⚠️ 必须带超时, 否则信号打不进来(见下)
    if not chunk:
        break
    buf += chunk
    while True:                           # 从字节流里切出完整 JPEG, 原样写文件
        a = buf.find(b"\xff\xd8\xff")
        b = buf.find(b"\xff\xd9", a + 2)
        if a < 0 or b < 0:
            break
        f.write(buf[a:b + 2]);  n += 1
        buf = buf[b + 2:]
```
实测 25 分钟 = 23723 帧 = 689MB，磁盘毫无压力。

**从 `.mjpg` 裁片段（三个坑，全踩过）**：
```bash
ffmpeg -y -framerate 16 -f mjpeg -i rec.mjpg \
  -vf "select='between(n,1216,2288)'" -r 16 \
  -c:v libx264 -preset veryfast -crf 23 -pix_fmt yuv420p -movflags +faststart clip.mp4
```
1. **`-framerate <实测fps>` 必须放在 `-i` 之前**。mjpeg 解复用器默认 25fps，不加这段，
   16fps 录的内容会被标成 25fps ⇒ **播放快 1.56 倍**，而且看不出错（帧数对、画面也对）。
   裁完用 `ffprobe -show_entries stream=r_frame_rate` 复核一下再交付。
2. **别用 `-ss <秒>` 放 `-i` 前**：对无索引的 raw mjpeg 会直接失败（输出 0 字节，
   还要从 stderr 里才发现）。要按时间裁就换算成帧号，用 `-vf select='between(n,A,B)'`；
   `-f mjpeg` 建议显式写上。
3. **`-r` 与 `-fps_mode passthrough` 不能同时给**（报 `specified together a non-CFR -vsync/-fps_mode,
   This is contradictory`）⇒ 二选一，要固定帧率就只给 `-r`。

**量「画面里有多少真帧」用同一帧占比**（比 fps 更能说明观感）：
```python
runs, cur = [], 0            # 连续"几乎相同"的帧长度
# 两帧灰度绝对差 < 0.15 → 视为重复；中位 run = med ⇒ 真实内容 ≈ 容器fps / med
```
实测：容器 16fps、中位 run = 2 ⇒ **真实内容 8.0fps**（静止场景则接近 16）。
这个数才是用户眼睛看到的帧率，用它验收、也用它对比改造前后（3.0 → 8.0）。

---

## ③ ROS 全速原始帧抓取（容器内，绕开 1Hz 解码节流）

```python
import os, json, time, numpy as np, rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from sensor_msgs.msg import Image

RAW, META, TMP = "/dev/shm/zmax_arm.raw", "/dev/shm/zmax_arm.meta", "/dev/shm/.arm.tmp"

class RawTap(Node):
    def __init__(self, topic):
        super().__init__("zmax_arm_raw_tap")
        q = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT,
                       history=HistoryPolicy.KEEP_LAST)
        # ⚠️ 不要 raw=True：那会拿到 CDR 序列化 bytes，没有 .encoding/.height
        self.create_subscription(Image, topic, self.cb, q)
        self.seq = 0

    def cb(self, msg):
        enc = (msg.encoding or "").lower()
        h, w, step = int(msg.height), int(msg.width), int(msg.step)
        data = bytes(msg.data)
        if enc in ("rgb8", "bgr8"):
            if step != w * 3:                       # 行有 padding 时逐行截取
                data = b"".join(data[i*step:i*step+w*3] for i in range(h))
            arr = np.frombuffer(data, np.uint8).reshape(h, w, 3)
            if enc == "rgb8":                       # 本机 cv2 是 BGR 口径
                arr = arr[:, :, ::-1]
            out, nc = np.ascontiguousarray(arr), 3
        elif enc in ("mono8", "8UC1"):
            if step != w:
                data = b"".join(data[i*step:i*step+w] for i in range(h))
            out = np.ascontiguousarray(np.frombuffer(data, np.uint8).reshape(h, w)[:, :, None])
            nc = 1
        else:
            return                                  # 不支持的编码: 只记元数据, 别崩
        # 原子写: 先写 tmp 再 replace, 否则工位机可能读到半帧
        with open(TMP, "wb") as f:
            f.write(out.tobytes())
        os.replace(TMP, RAW)
        self.seq += 1
        json.dump({"seq": self.seq, "w": w, "h": h, "nmask": nc, "enc": enc,
                   "ts": time.time(), "bytes": h*w*nc}, open(META + ".tmp", "w"))
        os.replace(META + ".tmp", META)
```

消费侧（工位机）只看 `meta` 的 `seq` 变没变 → 变了才读 `raw` → JPEG 编码：
```python
meta = json.load(open(META))
if meta["seq"] != last_seq:
    arr  = np.frombuffer(open(RAW, "rb").read(meta["w"]*meta["h"]*meta["nmask"]),
                         np.uint8).reshape(meta["h"], meta["w"], meta["nmask"])
    img  = arr if meta["nmask"] == 3 else cv2.cvtColor(arr[:, :, 0], cv2.COLOR_GRAY2BGR)
    ok, jpg = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
    last_seq = meta["seq"]
```

### 容器启动（⚠️ 三处易错）
```bash
sudo docker run -d --name zmax-arm-raw --restart unless-stopped \
  --network host -e ROS_DOMAIN_ID=0 \           # 与现役 tap 同 domain, 否则看不到话题
  -v /dev/shm:/dev/shm \                        # 不挂=工位机读不到帧文件
  -v <repo>/tools:/repo:ro \
  ros:humble-ros-base bash -lc \
  'source /opt/ros/*/setup.bash; exec python3 /repo/ros_arm_tap_raw.py'
```
- `ros:humble-ros-base` 自带 **numpy**，但**没有 cv2**、也**没有 image_transport** ⇒ 所以压缩放工位机本机做。
- 本机 docker 需要 **sudo**（非 root 用户默认 permission denied）。
- 验证落帧：`ls -la /dev/shm/zmax_arm.*` + `cat /dev/shm/zmax_arm.meta`，
  再观 10 秒 `seq` 增量算出真实 fps。

### 先探针再写码（省时）
```bash
ros2 topic hz /realsense/color/image_raw     # 相机真实帧率（本例 1.92Hz）
ros2 topic bw /realsense/color/image_raw     # 每帧 0.92MB / 链路 1.77MB/s
ros2 topic list | grep -iE 'image|color|depth'   # 是否有 /compressed 变体
```
**没有 `/compressed` 话题**就说明源头不压缩；要压得在 Orin 侧做 republish（需用户授权）。

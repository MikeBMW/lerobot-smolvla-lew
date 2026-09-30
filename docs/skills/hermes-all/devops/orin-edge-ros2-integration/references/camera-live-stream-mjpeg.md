# 相机实时视频流（压缩推流）— 完整配方

用途：把真机旁路调试时的两路画面（Orin 手臂相机 + 本机内置相机）压成低延迟 MJPEG 给人看。
组件：`tools/cam_live_stream.py`（本机 stdlib http.server，无需 flask）。

## 为什么是 MJPEG +「只发最新帧」

- MJPEG = `multipart/x-mixed-replace`，浏览器/WebView 原生支持，无需播放器、无需解码缓冲。
- 服务端为每路维护「最新一帧 + seq」；订阅循环发现 seq 没变就等，**永不做队列** ⇒ 不积压、不追帧。
- 两路各一条采集线程（各写自己的最新帧槽），HTTP 线程只读槽——采集慢不会拖累其他订阅者。

## 测量口径（先量再压）

```bash
# 源头：相机真实帧率与带宽（决定天花板）
sudo docker run --rm --network host -e ROS_DOMAIN_ID=0 --entrypoint bash ros:humble-ros-base -lc \
  'source /opt/ros/*/setup.bash; ros2 topic hz /realsense/color/image_raw; ros2 topic bw /realsense/color/image_raw'
# 落盘产物：tap 实际写图频率（8 秒内 mtime 变化次数 / 8）
# 压缩比：cv2.imencode('.jpg', im, [IMWRITE_JPEG_QUALITY, q]) 对同一帧量字节
```

实测（640×480 彩图）：原始 ROS Image 921KB/帧；tap 落盘 PNG 420KB；JPEG q60 24.5KB / q70 29.1KB / q80 37.0KB。
**q70 是体积与观感的平衡点**，面板场景不必更高。

## 交付流程

1. 启动：`setsid gui-venv311/bin/python tools/cam_live_stream.py --port 8791 --quality 70 --fps 15 > /tmp/cam_live.log 2>&1 &`
   （`--no-local` 可只推手臂那路；`--local-dev N` 指定 `/dev/videoN`；`--arm-src` 改手臂帧来源。）
2. 自证：`curl -s localhost:8791/stats` 看 fps / kb_per_frame / raw_kb_per_frame / compress_x / age_s。
3. 取快照并**验真**：`/snapshot/arm.jpg` → cv2 读图算灰度 std，`std>5` 才发；低于 5 说明黑帧/坏图，先修源头。
4. 交付：把带标注的快照发出去 + 给看板 URL（两个网段都给，别只给一个）。

## 排查顺序（画面不对时）

1. `/stats` 里 `online=false` → 该路源头没有帧（相机没出图 / 帧文件路径不对）。
2. `age_s` 很大但 `fps` 正常 → 源头本身延迟（相机帧率低或上游在节流），不是推流端问题。
3. `fps` 远低于相机帧率 → 采集侧在节流（tap 解码率 / 本机相机缓冲）。
4. 画面花/卡顿 → 降分辨率或降 q，别动「最新帧」策略（那是低延迟的根）。

## 坑

- **别把带宽当延迟**：链路占用 1-2% 时，压缩对**延迟**几乎无贡献，只对**下游显示**（手机/WiFi）有用。
  报实时性时必须先分清「带宽瓶颈」与「帧周期瓶颈」，否则会去优化一个不是瓶颈的东西。
- **相机帧率是硬上限**：源头 1.92Hz 时，任何压缩/加速都做不出 10fps 的画面。要真提帧率得改相机配置，
  那是动在役感知链，必须先取得现场授权。
- **上游采集器可能故意低频**（省 CPU 的 raw 订阅 + 低频解码），它比相机更慢——要真实时得绕开它，
  而不是在它的产物上做文章。
- **容器里未必有 cv2**：ROS 基础镜像通常只有 numpy。要么把原始帧写到共享内存、在本机（有 cv2 的 venv）压，
  要么另建带 opencv 的镜像。
- **交付的图必须自带状态**（源/尺寸/字节数/时间戳/帧龄）。画面本身要能回答「这是哪一路、多新」，
  否则用户会把旧帧当实时帧。

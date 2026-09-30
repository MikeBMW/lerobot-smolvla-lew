# 真机相机链路: 分清"设备层"与"ROS2 层" (RealSense D405, 2026-09-18 实测)

用户问「还要装什么驱动? 现在驱动不是好的么」时, **先分两层回答**, 别把过时结论当事实 ——
本次会话就是因为引用了旧版技能里"相机未插/未上电"的结论, 被用户当场纠正。

## 两层判据表 (Intel RealSense **D405**)

| 层 | 怎么查 | 实测结果 |
|---|---|---|
| 设备层 (内核 uvcvideo) | `ls /dev/video*` · `lsmod \| grep uvc` · `lsusb \| grep -i intel` | `/dev/video0-5` ✓ · `uvcvideo` 已加载 ✓ · `Intel(R) RealSense(TM) Depth Camera 405` (8086:0b5b) ✓ |
| ROS2 层 (谁在发话题) | `ros2 topic list \| grep -i realsense` + `ros2 topic info -v <t>` 看 Publisher | `/realsense/{color/image_raw, depth/image_rect_raw, color/camera_info, points}` **四个都有发布者** = 自研 **`realsense_source`** 节点 (Publisher count=1, QoS RELIABLE) |

**关键判据**: `ros2 pkg list | grep realsense` 为空 **≠ 驱动没起**。产线用自研发布节点,
**不需要 `realsense2_camera` 官方包**。只认 **Publisher count / 是否真有帧**。

## D405 的物理事实 (别问错方向)

- **主动红外双目** (左IR+右IR+RGB+点阵投射器), 但**只输出固件融合后的深度** (`16UC1`) + RGB (`bgr8`) ——
  **拿不到原始左右目视图** ⇒ 不能在本地重做双目匹配/在线自标定 (要裸 IR 得订 infrared 流)。
  对我们的 3D 定位链 (取 Z) 是够的。
- 短距量程 **0.07–1 m**, 适合工作台级精细操作。
- **深度读数必须先过 `depth_scale` 再解读**: 实测原始 uint16 换算出 2.3–22.2 m (**超出量程**)
  → 要么相机此刻对着远处, 要么 scale 未应用; **别把原始值当米数报出去**。
  判据 = 与现场视角比对 + `camera_info` 里的 scale。

## 直取一帧 (本机 ssh 过去, 不经 GUI、不碰任何控制话题)

```bash
ssh tashan@192.168.23.66 'bash -lc "export ROS_DOMAIN_ID=0; source /opt/ros/humble/setup.bash;
  python3 - <<PY
import rclpy, time
from rclpy.node import Node
from sensor_msgs.msg import Image
rclpy.init(); n = Node(\"grab\"); got = {}
for tag, topic in ((\"color\", \"/realsense/color/image_raw\"), (\"depth\", \"/realsense/depth/image_rect_raw\")):
    n.create_subscription(Image, topic,
        (lambda t: lambda m: got.setdefault(t, (m.width, m.height, m.encoding, len(m.data))))(tag), 10)
t0 = time.time()
while time.time()-t0 < 12 and len(got) < 2: rclpy.spin_once(n, timeout_sec=0.5)
print(got)
PY"'
```

实测: color **640×480 bgr8** (921,600 B) · depth **640×480 16UC1** (614,400 B) · 深度有效像素 **86%**。

## 把帧当证据交给用户时 (他不能看, 我也不能看)

- 先看第一帧前 16 字节 hex, 判断是不是全零 (全零 = 无效区/坏帧)。
- 落盘 PNG 后回传: 大文件走 base64 分节 (本机 scp 超过 100MB 会断) —— 帧只有几百 KB, 直接 base64 即可。
- 报规格 (`ffprobe`: 分辨率/编码/帧数/时长) + 用**通道均值/帧间差/唯一色数**自证非黑帧非静帧。
- 必须写明「我无法看图, 工艺细节 (目标在不在夹爪里 / 视角对不对 / 插没插到位) 请你目检」——
  该用户会目检画面细节, 也会当场戳穿假画面。
- 用户要"视频"时先确认**哪一个相机**: 数据集里的 `videos/observation.image/*.mp4` 与
  RealSense 实时流是**两回事**; 给错了会被直接指出「我说的是 realsense 的视频」。

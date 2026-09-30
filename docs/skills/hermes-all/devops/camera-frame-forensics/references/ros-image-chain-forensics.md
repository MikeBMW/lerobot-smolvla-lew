# ④ ROS/DDS 侧取证: 图一帧都没到订阅端 (话题在, 但没人发)

像素统计(①②③)只能判"**收到的**图黑不黑"。若订阅端**一帧都没收到**
(落盘文件帧龄几小时 / 计数器=0), 说明断在**发布端**, 走本节。

## 铁律 A: `ros2 topic list` 里有话题 ≠ 有人发
只要有**订阅者**存在, 话题就会出现在列表里 —— 你的订阅自己就能把它"撑"出来。
**判定只看 Publisher count:**
```
ros2 topic info -v /realsense/color/image_raw
  Type: sensor_msgs/msg/Image
  Publisher count: 0            ← 源头没人发 (决定性判据)
  Subscription count: 1         ← 这个就是我自己
  Node name: ss_remote_tap ... Endpoint type: SUBSCRIPTION   ← 坐实"唯一的订阅者是我"
```
一手实测(2026-09-20): 话题列表中有 `/realsense/color/image_raw` 与
`/foundationpose/tray_reference/debug_image` 两个 Image 话题, 两者 **Publisher count 全 0**,
订阅者都是我方的只读 tap ⇒ 我侧永远 recv.img=0, 一帧未收。

## 铁律 B: **进程活着 ≠ 在 ROS 图里**
源头进程可能"活着但已僵死": 不在节点列表、不出帧、握着设备不放。
三连取证(全部只读, 适合产线设备):
```bash
ps -o pid,stat,etime,rss,cmd -p <pid>      # STAT=S(sleeping)/Z(zombie), ELAPSED 说明起了多久
ros2 node list | grep -i <node>            # 图里没有它 ⇒ 僵死/未完成初始化 (决定性)
ls -l /proc/<pid>/fd | grep -E 'video|media'   # 是否独占握着 /dev/video*
cat /proc/<pid>/wchan                      # futex_wait_queue_me = 卡在等锁
for t in $(ls /proc/<pid>/task | head -4); do cat /proc/<pid>/task/$t/wchan; done  # 全线程都卡 ⇒ 死锁态
```
一手实测: `realsense_source` pid 4694 `STAT=Sl` 已起 1d2h、**不在 `ros2 node list`**、
独占 6 个 `/dev/video*`(fd 23/26/27/30/31/34)、26 线程全部 `futex_wait_queue_me`
⇒ 存活但僵死的相机节点。硬件(USB 8086:0b5b RealSense D405)与 `/dev/video0~5` 都正常 ⇒ **不是硬件、不是网络**。

## 铁律 B': 同族但不同恢复路径 —— 节点**崩了**(不是僵死), 先看 launch 日志的 exit code
```
launch log: [realsense_source-8] process has died [pid ..., exit code -11, cmd '.../camera/realsense_source ...']
```
- `-11` = **段错误** · `-6` = abort · `-9` = 被杀/OOM。崩溃后进程**真没了**(`/proc/<pid>` 查不到),
  与"活着但僵死"是两条路, 但恢复口都一样: **接 铁律 C 的最小干预重启**(用 `/tmp/launch_params_*` 原参数起回)。
- 实测坑(值得记): 节点崩了之后, 我在**订阅侧**反复调参(BEST_EFFORT、`raw=True`、直接 echo)全部无效 ——
  **"话题在、BEST_EFFORT 也是 0 帧"就该立即翻 launch 日志找 exit code**, 而不是继续怀疑订阅。
  判定顺序: `topic list` 有 → `topic info -v` 看 Publisher count → 0 就翻日志看是**僵死**还是**崩溃**。

## 铁律 C: 动之前先量爆炸半径 (查 launch 里的 respawn/required)
在 launch 的 py/yaml 里搜该节点的构造:
```python
Node(package="camera", executable="realsense_source", name="realsense_source",
     output="screen", parameters=[cfg], condition=IfCondition(...))     # ← 无 respawn / 非 required
```
- **普通 Node(无 respawn / 非 required)**: 杀掉**不会自愈**, 也**不会带崩线体**
  ⇒ 恢复只能靠**重启该节点或整条 launch** (别指望 `kill` 能修好)。
- **`required=True`**: 杀掉会**带崩整条 launch**(含机器人驱动) ⇒ 生产线上务必先查再动。
- 参数文件常留在 `/tmp/launch_params_*`: 从 `ps` 的 cmdline 取到 `--params-file`, 文件还在
  就能**用它原参数 1:1 起回同一个产线二进制**(不新增程序、不改代码) —— 最小干预重启口径。

## 铁律 D: 备选眼睛 —— 挪本机相机比动产线便宜
产线侧相机链路断、又不许动产线设备时, **先确认本机 USB 相机能不能看到工位**:
```python
cap = cv2.VideoCapture(0, cv2.CAP_V4L2)      # 抓 5 帧丢弃最旧的
ok, f = cap.read(); print(f.shape, f.mean(), f.std())   # std<5 ⇒ 黑/无效帧
cv2.imwrite(os.path.expanduser("~/zmax_ss_remote/local_cam_test.png"), f)
```
再把这张真图交给 VLM 判读(见 `smolvlm-perception-integration` / 画布 🧿 节点):
一手实测: 1280x720 `mean=57.7 / std=43.5`(有效帧), VLM 判读出
`白色机械臂 / 铝型材支架 / 黑色托盘 / 黄色立柱 / 背景百叶窗` ⇒ **本机相机确实对着产线**,
只是"太远或太小 / 被前景网眼椅背遮挡 / 偏暗" ⇒ 现场挪相机/移遮挡即可恢复视觉, 全程零接触产线。

## 常见坑
- `ros2 topic hz --qos-reliability best_effort` → `unrecognized arguments` (humble 的 hz 不吃这个参数)。
  要看 QoS 用 `ros2 topic info -v <topic>` (Reliability: BEST_EFFORT 在端点信息里);
  sensor 话题订阅端用 BEST_EFFORT 才收得到(我方 tap 即 `raw=True` + BEST_EFFORT 订阅)。
  ⚠️ **但 `raw=True` 只适合"只数帧/只转发字节"**: 回调拿到的是 **CDR 序列化 bytes**,
  没有 `.encoding` / `.height` / `.step` 字段，一读就报
  `'bytes' object has no attribute 'encoding'`。**一需要像素或元数据就必须去掉 `raw=True`**,
  让 rclpy 正常反序列化（想省 CPU 的快路径和想读字段的慢路径不能兼得）。
  推流/压缩场景的全速订阅写法见 `low-latency-camera-streaming` 技能。
- `/gripper_pos` 这类话题**同名双类型**(Float32 / Float64) ⇒ `ros2 topic echo --once` 会歧义失败, 别据此判"话题死了"。
- 服务列表里有名字 ≠ 有服务端: `/hmi/snapshot` 在 `ros2 service list` 里, 但调用 30s 超时(无服务端)
  ⇒ 服务端可能根本没起(与"话题只被订阅撑着"是同一类假象)。
- 日志里"某相机服务 offline"(如梅卡点云服务)只描述**那条**链路, 不要外推成"所有相机都坏了"。

## 判据速查
| 现象 | 结论 |
|---|---|
| Publisher count: 0 (订阅数是自己) | 源头无发布者 ⇒ 发布端问题, 与像素/曝光无关 |
| 进程在但 `ros2 node list` 没有 | 僵死/初始化未完成 ⇒ 需重启该节点 |
| `/proc/<pid>/fd` 握着 /dev/video* | 设备被这只僵死进程独占 ⇒ 别人也打不开 |
| 无 respawn 的普通 Node | 杀它不自愈、不带崩; 恢复=重启节点/整条 launch |
| 话题在、BEST_EFFORT 订阅也 0 帧 | 别继续调订阅 ⇒ 翻 launch 日志找 `process has died … exit code`(节点崩了, 重启节点) |
| 本机相机 std>5 + VLM 认得出工位 | 可用作备选眼睛(零接触产线) |

---
name: orin-lan-direct-access
description: "Use when 本机直连 Orin 产线局域网/拉 Orin 录制数据。"
version: 1.0.0
author: agent
tags: [zmax, orin, network, rosbag2, data-loop]
platforms: [linux]
---

# 本机 → Orin 产线局域网 直连 (2026-09-16 实测通)

**旧铁律作废**: 以前记的是「本地到不了 192.168.23.x，必须绕 ECS/Mac」。本机(ThinkBook)
插 USB 千兆网卡后**可直连** Orin 局域网，延迟 0.5ms。WSL 那台仍是 172.18.x，不适用。

## 硬件前提
ThinkBook 无板载 RJ45 → 必须 **RJ45→USB 适配器**（实测 RTL8153 / driver `r8152`，千兆）。
插上后出现 `enx<MAC>` 接口（名称随适配器 MAC 变，换适配器要改 netplan 文件名/IP 段）。

## 一次性配置（netplan, 持久）
`/etc/netplan/99-orin-lan.yaml`（权限 600 root）:
```yaml
network:
  version: 2
  renderer: NetworkManager
  ethernets:
    enx00e04c0c32a0:
      dhcp4: false
      dhcp6: false
      addresses: [192.168.23.50/24]
      # 不设网关/默认路由 → 上网继续走 WiFi, 不打断 datadrive.world WS / 飞书
      optional: true
```
```bash
sudo netplan generate && sudo netplan apply
sudo nmcli connection up netplan-enx00e04c0c32a0
# 关掉 cloud-init 的 en* DHCP catch-all (它先抢到设备, 无 DHCP 时一直 connecting)
sudo nmcli connection modify netplan-zz-all-en connection.autoconnect no
sudo nmcli connection modify netplan-enx00e04c0c32a0 connection.autoconnect-priority 100
```
坑: ① `netplan apply` 会顺带弹一下 WiFi（实测 Corp-Office → Corp-Guest），完事 `nmcli connection up <原名>` 恢复即可。
② catch-all 来自 `/etc/netplan/50-cloud-init.yaml`（`match: name: "en*"`），没法排除，只能靠 autoconnect=no + 优先级。
③ nmcli 对 netplan 管理的 profile 的改动会写回 `/etc/netplan/90-NM-<uuid>.yaml` → 重启仍生效。
④ 该网段无 DHCP → 不配静态 IP 会一直卡 "connecting (getting IP configuration)"。

## ⚠️ 大坑: 静态 IP 被 NetworkManager 抢到「摄像头 RNDIS 口」(2026-09-20 实测踩到)
症状: `enx00e04c0c32a0`(RTL8153 真网卡) **carrier=1/link 1000 但无 IP** → 整个 192.168.23.0/24 不可达
(ARP 全 FAILED, Orin 也不回); 而 `enx1ead2db2be1c`(板载摄像头 WT15 的 RNDIS 网络口, `rndis_host` 驱动)
上却挂着 192.168.23.50/24。`ip neigh` 那个口扫一圈全是 FAILED。
根因: `/etc/netplan/90-NM-<uuid>.yaml` 里 NM 回写的 profile 是 **`match: {}`**(空 match = 匹配任意以太网)
+ `autoconnect-priority: 100` → 开机时它抢到先出现的 RNDIS 口, 真网卡反而没 profile。
诊断三步:
```bash
for i in /sys/class/net/enx*; do echo $i $(cat $i/carrier) $(cat $i/speed); done  # 谁真联着交换机
nmcli -t -f DEVICE,STATE,CONNECTION device status   # 静态IP落在哪个设备上
ip route get 192.168.23.66                          # 去 Orin 实际走哪块网卡
```
修复(实测有效, **不需要 `netplan apply`, WiFi 不断**):
```bash
sudo cp -a /etc/netplan ~/netplan_backup                    # 留旧环境
sudo mv /etc/netplan/90-NM-<uuid>.yaml <备份目录>/          # 移走那个 match:{} 的坏 profile
sudo netplan generate && sudo nmcli connection reload
sudo nmcli device disconnect enx1ead2db2be1c                # 从错误设备上摘掉
nmcli connection up netplan-enx00e04c0c32a0                 # 由 99-orin-lan.yaml 生成的、按接口名绑定的 profile
```
关键: **必须在 profile 非激活状态下改 `connection.interface-name`**, 否则 nmcli 静默不生效
(实测改完仍是 `--`), 且 NM 会把 netplan 当作权威源, 用 `netplan generate` 重生成比 nmcli 改更靠谱。
`nmcli connection up` 后 profile 仍会跑回错误设备 —— 所以真正要动的是那个 yaml 文件。
验证: `.50` 只出现在真网卡上; `ip route get 192.168.23.66` 走 `enx00e04c0c32a0`; 默认路由仍走 WiFi
(`10.163.147.254 dev wlp0s20f3`); 并确认 `~/.config/autostart` 与 `crontab` 里没有会改网卡的脚本。

## ⚠️⚠️ 最大的坑: DDS 多播被默认路由(WiFi)抢走 → 跨机订阅「全 0」但链路其实是通的 (2026-09-20 实测)
症状: 本机 Docker tap 容器 (`ss-remote-tap`, `--network host`, ROS_DOMAIN_ID=0) 跑得好好的,
`status.json` 里 `外部队列发布者(Orin侧)` 却**全是 0**, `recv` 全 0, 落盘 `state_*.jsonl` 几十万行**全是 null**
(tcp/jpos/ft/gripper 全 null), 而 Orin 侧 `ros2 topic hz /robot/tcp_pose` 明明 42-50Hz。
根因: 本机是**双网卡**(WiFi 有默认路由 + USB 千兆到产线网 192.168.23.0/24)。
ROS2/FastDDS 的**发现多播**按默认多播路由走 —— `ip route get 239.255.0.1` 显示 `dev wlp0s20f3`(WiFi),
于是发现包发到公司网, 永远到不了产线交换机上的 Orin → 容器里"看不到任何外部发布者"。
**关键区分(别误判成 Orin 没发)**: 从 Orin 自己看 `ros2 topic hz` 有速率, 从本机容器看 pubs=0 = 本机发现瞎了。
诊断三步:
```bash
ip route get 239.255.0.1                      # dev 是 wlp0s20f3 → 中招
sudo docker exec ss-remote-tap bash -lc 'source /opt/ros/humble/setup.bash; ros2 topic list'   # 只有本地几个话题
```
修复(持久, 已写进 `/etc/netplan/99-orin-lan.yaml`):
```yaml
      routes:
        - to: 239.255.0.0/8     # 多播钉到产线网卡
          scope: link
```
```bash
sudo netplan generate && sudo nmcli connection reload && sudo nmcli connection up netplan-enx00e04c0c32a0
ip route get 239.255.0.1        # 现在 dev=enx00e04c0c32a0 ✓  默认路由仍在 WiFi ✓
```
**改完必须重启容器**: 已存在的 DDS participant 在创建时就定好了收发 locator, 加路由不会让老进程重新通告 →
`sudo docker rm -f ss-remote-tap` 再按原命令行 `docker run -d` 起来, 之后 `status.json` 立刻 `recv.tcp/ft` 涨到千级、
`外部队列发布者` 全 1、jsonl 里 `tcp:[x,y,z]`+`tcp_quat`+`frame=base_link` 有真值。
坑中坑: 容器内 `ros2 topic info /robot/tcp_pose` 可能仍报 `Publisher count: 0`(远端 BEST_EFFORT 计数器),
**以 `ros2 topic hz` 有速率 或 status.json 的 recv 计数为准**, 别被 info 的 0 骗回去继续查网络。
另: `-e FASTRTPS_DEFAULT_PROFILES_FILE` 白名单 XML 也能修, 但要改启动器+挂文件; **先试多播路由这一招(零代码)**。

### ⚠️ 开机竞态: DDS 参与者先于产线网卡地址创建 → 发现全 0 且**不自愈** (2026-09-21 实测)
症状与上面那条一样 (`status.json` recv 全 0 / 外部发布者全 0 / `cam_rs.png` 停留在上次关机前),
但**多播路由已经是对的**(`ip route get 239.255.0.1` → dev=enx00e04c0c32a0),Orin 侧 `ros2 topic hz` 有速率。
判据(一眼分真假): 在本机 tap 容器里**新起一个** CLI 进程能发现发布者并收到数据, 而**开机自启的 tap 进程**永远 0
→ 不是网络问题, 是那个老 participant 在网卡地址就绪前就创建了, FastDDS 不会事后重扫网口。
```bash
# 0) Orin 侧确认确实在发(别只看本机)
ssh tashan@192.168.23.66 'bash -lc "source /opt/ros/humble/setup.bash; export ROS_DOMAIN_ID=0; timeout 10 ros2 topic hz /realsense/color/image_raw"'
# 1) 容器内另起进程复核(能收到=本机链路通, 老进程瞎了)
sudo docker exec ss-remote-tap bash -lc 'source /opt/ros/humble/setup.bash; export ROS_DOMAIN_ID=0; ros2 daemon stop; sleep 3; timeout 14 ros2 topic hz /realsense/color/image_raw; timeout 12 ros2 node list'
# 2) 修复: 重启那个老进程(重启后立刻恢复, recv.img 由 0 → 涨)
sudo systemctl restart ss-remote-tap
```
**永久修(已落地)**: `/etc/systemd/system/ss-remote-tap.service` 加
`ExecStartPre=/usr/local/bin/ss_tap_netwait.sh` —— 启动前 `ip route get 192.168.23.66` 轮询到 `src=192.168.23.50`
才放行(最多等 120s, 超时仅告警不阻断)。开机日志可见 `[netwait] 直连链路就绪 (src=192.168.23.50, 第1次探测)`。
副作用提醒: 关机放置后开机,**先看 `cam_rs.png` 时间戳与 `status.json.recv.img`**, 别以为"服务 active 就等于链通"。

## 地址表（小芳 2026-09-16 确认）
| 设备 | 地址 |
|---|---|
| 本机(静静/4060机) | 192.168.23.50 (建议值) |
| Mac（也是网关, 能 NAT） | 192.168.23.1 |
| 工控机 | 192.168.23.23 |
| **Orin** | **192.168.23.66**（enP8p1s0, ssh 用户 `tashan`） |
| 珞石机器人 | 192.168.23.160 |

接法: 插现场交换机空口；**不要拔 Orin 的线**。Mac 的 ICMP 可能不回（ping 不通≠不通）。

## Orin 侧可用服务
```bash
ssh tashan@192.168.23.66                     # 密码 ts123
curl http://192.168.23.66:8765/health        # Orin Gateway (源码 ~/.zmax/orin_gateway.py)
#   /joints /record/start /record/stop /record/status /record/latest /record/download /disk /record/cleanup /disk/guard
curl http://192.168.23.66:8000/openapi.json  # Tashan Robot HMI (产线控制)
```
端口: 22 / 8000 / 8765 开; 80 / 5000 / 1883 / 9090 关。Orin 上长期跑 `ss_infer_service.py`(状态空间推理)与 `orin_gateway.py`。

## 拉真录制数据（rosbag2）
Orin 每 ~11 分钟自动录一段到 `~/.zmax/mcap/record_<unix_ts>/`（.db3 + metadata.yaml），话题:
`/real_joint_states`(JointState ~90Hz) `/robot/force_torque`(WrenchStamped) `/gripper_pos`(Float32)
`/motion/active_states`(String) `/joint_states`(常 0 条)。单段约 24s / 1.2MB。
```bash
curl -s http://192.168.23.66:8765/record/latest   # 最新一段 dir/name/size_mb
```
**解析务必用 rosbag2_py**（手写 CDR 极易错; 且 rosbag2 sqlite 布局是 `topics`/`messages` 表，不是按话题建表）:
```python
from rosbag2_py import SequentialReader, StorageOptions, ConverterOptions
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message
r = SequentialReader()
r.open(StorageOptions(uri=rec, storage_id='sqlite3'),
       ConverterOptions(input_serialization_format='cdr', output_serialization_format='cdr'))
while r.has_next():
    topic, data, ts = r.read_next()
    msg = deserialize_message(data, get_message('sensor_msgs/msg/JointState'))
```
```bash
ssh tashan@192.168.23.66 'bash -lc "source /opt/ros/humble/setup.bash && python3 /tmp/bag_motion.py <record_dir>"'
```

## Orin 硬件栈体检（2026-09-16 实测, 硬件工具箱 VEH.0.86 / 硬件页 VEH.3 后端）
⚠️ **ROS_DOMAIN_ID 是 0（不是 23！）** —— 机器人驱动/录制都用 domain 0（`orin_gateway.py:45`
`export ROS_DOMAIN_ID=0 ros2 bag record ...`）。用 23 查只会看到 /rosout，误判"驱动没起"。
```bash
ssh tashan@192.168.23.66 'bash -lc "export ROS_DOMAIN_ID=0; source /opt/ros/humble/setup.bash;
  ros2 node list; ros2 topic list -t; ros2 service list -t | grep gripper;
  for t in /real_joint_states /robot/force_torque /gripper_pos /barcode_scanner/status /tower_light/status; do
    echo -n \"$t \"; timeout 6 ros2 topic hz $t 2>/dev/null | grep -m1 \"average rate\"; done"'
```
实测基线（正常时该看到）: 18 节点在跑（robot_driver/gripper_driver/honeywell_scanner/tactile_force_node/
tower_light/motion/vision*/pointcloud_receiver/orin_shadow/ss_collector/hmi_v1_tashan_bridge + 两个 state_publisher）。
速率: `/real_joint_states` **100.8Hz**（珞石 XMS5-R800 本体）· `/robot/joint_states` 49.5 · `/robot/force_torque` 50.5（六维力）
· `/gripper_pos` 12.1 · `/barcode_scanner/status` 1.0 · `/tower_light/status` 1.0（state=complete, 口 `/dev/serial/by-id/usb-Artery_LED_*`）
· `/robot_status` 2.2。服务 `/gripper_driver [interfaces/srv/GripperSrv]` 在线（**别随手调，会真动夹爪**）。
串口: ttyACM0=Honeywell 3320g 扫码枪 / ttyACM1=Artery 塔灯 / ttyUSB0=FTDI FT232R。
**已知易失项**: `/realsense/*` 与 `/ply_pointcloud`（Publisher=0 → 相机未插/未上电，视觉 4 节点空转）·
`/tactile_sensor`（Publisher=1 但静默，需确认是否仅接触时发布）· `/motion/active_states`（无消息 = 装配状态机没跑，
这也是"闭环拿到的数据全是 IDLE/静止"的上游原因）· `/usb_estop`、`/physical_estop`（事件型，静默正常，验证要现场按一下）。
设备侧: `lsusb | grep -i realtek|intel`、`ls /dev/video*`、`ls -l /dev/serial/by-id/`。

## 「闭环空转」判据（比连通更重要）
2026-09-16 实测: Orin 123 段录制 (08-10 → 09-16) **六个关节 Δ=0.0000**，恒为
0.1602/-0.0627/-2.5433/1.4469/0.4351/-0.6976，与 WS 包 action 逐位相同、labels 全 IDLE
→ 现场机械臂本体一直没动。**六维力是活的**（Δ Fy≈3.4 / Fz≈3.4）说明采集链路正常；
`/gripper_pos` 恒 1000.0000 可疑（像占位值），需向小芳确认。
⇒ 数据全静止时: builder 过滤 IDLE → 0 帧 → 无 parquet → 训练秒崩。
**先量行程 Δ 再怀疑代码**，别因为"训练失败"去改训练。
配套坑: `tools/auto_loop.py::build_dataset()` 曾以 `(data/orin_6d).exists()` 为判据（空壳目录也 True，
把真因藏成"训练失败") — 已改为判 `data/chunk-000/*.parquet` 并回显 builder 尾部日志。

## ⚠️ rclpy 定时器会被时钟回拨冻死 → 真机画面"假采集" (2026-09-23 实证)

症状: tap 容器在跑、`state_*.jsonl` 10Hz 照写、`n["img"]` 计数照涨, 但 **cam_rs.png 不再更新**
(冻在某一刻), 画布「连接摄像头」最后报连接失败。

定位三步 (照抄):
```bash
# ① tap 自证: 最后一次成功解码的 meta (tm/age 不动 = 解码定时器死了)
python3 -c "import json,os;p='/home/ubuntu/zmax_ss_remote/state_20260923.jsonl'
ln=open(p,'rb').read()[-40000:].decode('utf-8','ignore').strip().split('\n')[-1]
print(json.loads(ln)['image'])"
# ② 独立探针 (同容器新进程: 订阅→反序列化→解码→写盘) tools/tap_img_probe.py
sudo docker exec -e ROS_DOMAIN_ID=0 -e SS_OUT=/out ss-remote-tap bash -lc \
  'source /opt/ros/humble/setup.bash && python3 /repo/tools/tap_img_probe.py /realsense/color/image_raw'
# ③ 回拨量 = (旧 meta.t) − (当前样本 t): 本次 1790183674 − 1790157975 = 25699s = 7.14h
```
真机相机实测 (2026-09-23): `/realsense/color/image_raw` **Publisher=1 在推流**, bgr8 640x480 step1920,
**帧率仅 ~0.37Hz** (2.4~3.1s/帧) —— 别按 30fps 假设; 画布 1.5s 轮询有时会读到同一帧属正常。

根因: **rclpy `create_timer` 按墙钟算"下次触发时刻"**, NTP 回拨 7h 后该时刻落到未来 7h → 回调
**永久不再触发**; 订阅回调 (cb_img) 不依赖定时器照常跑 ⇒ 假采集。(09-18 同一事故咬的是
**新鲜度判据**, 这次咬**定时器**。纪律: 节拍一律 monotonic。)

修法 (已落地 `tools/ss_remote_tap.py`): 删 `create_timer(1.0, _tick_img)` / `create_timer(5.0, _count_pubs)`,
主循环每轮调 `n.tick_monotonic()` (内部 monotonic 分频 1Hz 图像 / 5s 发布者计数)。重启 tap 生效:
```bash
sudo docker rm -f ss-remote-tap && sudo docker run -d --rm --name ss-remote-tap --network host \
  -e ROS_DOMAIN_ID=0 -e SS_OUT=/out -e SS_INFER_URL=http://127.0.0.1:8790/infer \
  -v /home/ubuntu/lerobot-smolvla-lew:/repo:ro -v /home/ubuntu/zmax_ss_remote:/out \
  ros:humble-ros-base bash -c 'source /opt/ros/humble/setup.bash && exec python3 /repo/tools/ss_remote_tap.py --rate 10'
```
验收: `cam_rs.png` 帧龄 ≤3s 且 mtime 前进, meta `saved=true std≈65 age<3` (实测修复后 1.8~1.9s ✓)。

## 画布「连接摄像头」失败的三条同时不通 (2026-09-23 实测)
① 真机帧: 上面那条 (tap 定时器) → cam_rs.png 冻住;
② 远端快照 `https://datadrive.world/api/snapshot/latest` **超时** (站点根也超时; 本机出网正常
   baidu=200/1.1.1.1 通) → ECS 侧问题, 非本机网络;
③ 本地兜底全废: cam_rs.png 因 mtime 在**未来**(回拨前落盘) 被 `age<-1.0 → 拒用`;
   cam_local.png 是几天前旧帧(>10s); 本机 /dev/video0、video2 实拍**全黑**(mean 1.3/0.0)。
GUI 逻辑 (`studio.py::_cam_connect/_cam_local_frame`): 远端失败→本地新鲜帧(≤10s)兜底→都没有才报
「❌ 连接失败」。所以修好 ① ③ 之后, 即使 ② 没恢复, 也应显示「🟡 已连接·本地回退 · 帧龄 x.xs」。


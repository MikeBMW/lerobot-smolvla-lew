# A1 · Orin → 云 状态上行 · 已部署 (2026-09-26, 老倪授权 A1~A9)

## 现状 (实测)
```
云端 https://datadrive.world/api/relay/orin/status:
  online   = true          (此前一直 false —— 云端看不到机器人侧)
  last_seen= 每 5s 更新
  cpu_temp_c= 60.7~61.1    mem_used_mb/total = ~9900/15642    load1 ~5
  robot_stack = {robot_driver: true, motion: true}     ← 产线双进程在跑
  robot    = {power_state: on, operation_state: idle, has_error: true}   ← 只读订阅 /robot_status
  infer_count / model = null   ← **Orin 上没有推理服务**(生产栈=robot_driver+motion), 如实标 null,
                                  不编 0/假模型名 (云端能区分"没读到"与"读到 0")
```

## 部署内容
| 位置 | 内容 |
|---|---|
| Orin `/home/tashan/zmax_orin_uplink.py` | 只读遥测上行 (stdlib only · 5s 心跳 + 30s 采机器人状态并**粘住**随每次心跳发出) |
| Orin `/etc/systemd/system/zmax-orin-uplink.service` | `User=tashan` · `Restart=always` · **CPUQuota=15% · MemoryMax=200M · Nice=10** (不打搅产线) |
| 本机 `tools/orin_uplink.py` · `tools/zmax-orin-uplink.service` | 同源留档 |
| ECS `/root/zmax-relay/zmax_relay.py` | `/orin/heartbeat` 改为**全量保存**上传字段 (原来只白名单 7 个键 → 温度/内存/robot 被丢) |

## 红线遵守
- **只读**: 读 /proc /sys + `ros2 topic echo --once` 订阅; **零动作**(不调 service/不发 topic/不碰 robot_driver/motion)
- 资源护栏: CPU 15% / 内存 200M / Nice 10; ros2 采样 30s 一次 (非 5s)
- 既有端点回归全 200 (status / hil/state / agent/status / orin/status)

## 回滚 (一条命令, 无残留)
```bash
ssh tashan@192.168.23.66 'echo <pwd> | sudo -S systemctl disable --now zmax-orin-uplink && rm -f /home/tashan/zmax_orin_uplink.py /etc/systemd/system/zmax-orin-uplink.service'
```

## 踩到的 3 个坑 (已修, 留档)
1. `robot_status` 消息很长会被**截断** → 不能 `json.loads`, 改**纯字符串查找**取字段
2. 只有每 30s 那次带 robot, 其余 5s 心跳发 `robot:null` → **把云端好数据覆盖成 null** → 改"记住上次采样每次带上"(附 `robot_ts`)
3. 服务上下文 DDS 发现慢 → `timeout 8` 取不到 → 改 20s + `--no-daemon`

# Orin → 云 状态上行 · 现场执行清单 (2026-09-26)

> 背景: 本机(4060)只读订阅 Orin ROS 是活的(tap 帧龄 0.1s), **但云端看不到机器人流** ——
> `/api/relay/orin/status` 实测 = `{"online": false, "infer_count": 0, "model": null}`。
> 云端 relay 里只有 `4060_hw` 与 `mac_hw` 两类包 ⇒ **Orin 侧没有任何上行**。
> 本清单让现场把这一段接上; 全程**只读状态, 不下发任何机器人动作**。

## 一、链路契约 (来自 ECS 中转真源 `zmax_relay.py`, 已本机实测)
```
上报: POST https://datadrive.world/api/relay/orin/heartbeat
      body: {"online":true,"role":"orin","model":"<模型名>","infer_count":N,
             "last_infer_ms":x,"uptime":s,"hw":{...},"note":"...","ts":"..."}
      ← {"ok": true}                    (2026-09-26 10:13:58 实测通过)
回读: GET  https://datadrive.world/api/relay/orin/status
      ← {"online":false|true,"model":...,"last_seen":"HH:MM:SS","infer_count":N,...}
```
脚本已随包交付: **`tools/orin_state_upload.py`** (本机干跑已验证载荷结构, 见下)。

## 二、现场步骤 (需现场授权后执行)
```bash
# 0) 前置: Orin 能出网 (curl 通 datadrive.world) + 有 python3
curl -s -m 8 -o /dev/null -w '%{http_code}\n' https://datadrive.world/api/relay/orin/status   # 期望 200

# 1) 拷贝脚本 (从 4060 或仓库取同版本)
scp tools/orin_state_upload.py <orin用户>@192.168.23.66:/home/nvidia/zmax/     # 路径按现场实际

# 2) 干跑: 只打印载荷, 不上传 —— 先确认 model / infer_count 有真值
python3 /home/nvidia/zmax/orin_state_upload.py --dry-run

# 3) 单次上报 + 云端回读
python3 /home/nvidia/zmax/orin_state_upload.py --once
curl -s https://datadrive.world/api/relay/orin/status    # 期望 online=true, model 非 null, infer_count>0

# 4) 常驻 (建议 systemd; 见下 unit 模板) —— 每 10s 一次
python3 /home/nvidia/zmax/orin_state_upload.py --interval 10
```

## 三、systemd unit 模板 (放 `/etc/systemd/system/zmax-orin-uplink.service`)
```ini
[Unit]
Description=Z-MAX Orin 状态上行 (只读本机状态 → ECS 中转)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=nvidia
Environment=PYTHONUNBUFFERED=1
Environment=ZMAX_ORIN_INFER=http://127.0.0.1:8790/health   # 按现场推理服务端口改
ExecStart=/usr/bin/python3 /home/nvidia/zmax/orin_state_upload.py --interval 10
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```
启用: `sudo systemctl daemon-reload && sudo systemctl enable --now zmax-orin-uplink`

## 四、验收判据 (现场当场可验)
1. `--dry-run` 里 `model` 非空、`infer_count` > 0 (说明读到了本机推理服务的真值)
2. 上报后 `GET /api/relay/orin/status` → `online=true` 且 `infer_count` 随推理增长 (隔 30s 看两次)
3. 云端 APP/控制台「DDS 节点/硬件资源」里出现 Orin 行 (数据源显示 ECS relay)
4. 断开 Orin 上行后 30s 内云端 `online` 回落 false (= 心跳陈旧判定生效, 不是永久缓存)

## 五、排障表
| 现象 | 排查 |
|---|---|
| `--dry-run` 里 model=null / infer_count=-1 | 推理服务端口不对 → 改 `--infer-url`; 或本机推理没起 |
| POST 超时 / 证书错 | Orin 出网受限 → 检查 DNS 与 443 出口; 可临时走 nginx 反代端口 |
| POST 返回 404 | 中转版本旧 → 需 ECS 上是带 `/orin/heartbeat` 的版本 (本机已是) |
| 状态里 online=true 但 infer_count 不涨 | 心跳真实, 推理没在跑 → 属正常 (分开看 online 与 infer_count) |
| 想停 | `sudo systemctl disable --now zmax-orin-uplink` + 删脚本 (无残留) |

## 六、红线 (老倪口径)
- **Orin 零自研零自启**: 本清单只交付现场操作手执行, 4060 侧不擅自部署/启动 Orin 服务
- 脚本**只读**本机状态 (推理健康 + 内存/温度), **不下发任何机器人动作**, 不碰 ROS 控制话题
- 不上报假数据: 拿不到的字段一律 null/-1 (云端能看出"没读到"而不是"读到 0")

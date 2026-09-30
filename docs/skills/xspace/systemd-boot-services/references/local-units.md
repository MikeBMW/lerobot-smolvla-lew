# 本机(4060 工位机)已落地 unit 清单 — 各自口径与红线

> 只列"开机自动跑/常驻"的, 一次性工具不在此。核验用 `scripts/verify_service.sh`。

| unit | 形态 | 干什么 | 核验点 / 红线 |
|---|---|---|---|
| `zmax-net-optimize.service` | oneshot | 每次开机: 应用网络旋钮(sysctl.d/99-zmax-net) + 断言 WiFi 省电 off + DNS `flush-caches`&预热 5 域 + 体检落台账 | `reports/net_boot_optimize_<YYYYMMDD>.jsonl` 每开机一行; 见技能 `linux-network-perf-boot` |
| `aoi-feishu-push.service` | simple | 常驻**只读**轮询工控机 `/last_result`, 有新拍照才把裁减图推飞书 | 红线: **绝不触发拍照**(不为推送连拍产线); 日志首行应见 `👀 实时监听 …(每 8s 轮询, 只读不拍照)` |
| `ss-local-infer.service` | — | 4060 侧状态空间推理服务 `127.0.0.1:8790` | `/health` 返回 `online:true` + `infer_count` 增速(~9Hz) |
| `ss-remote-tap.service` | — | 只读订阅 Orin 产线感知(Orin 侧零程序) | 红线: Orin 零自研零自启 |
| `ss-bypass.service` | — | 状态空间影子旁路(零下行不接管) | — |
| `ss-yolo-bypass.service` | — | 真机图像 → 光模块检出(只出可视化, 零下行) | 在役权重是软链 `models/yolo_peg_live.pt` |
| `zmax-data-mount.service` | oneshot | U盘启动时 bind E 盘公共数据目录 | 交付前确认数据盘已挂 |
| `zmax-studio.service` (systemd **--user**) | simple | PyQt5 控制台 XSpace Studio | **`Restart=no` 是用户 2026-09-17 定档**: 关窗口后不许再弹回来 → 控制台只人工启动; 开机时它可能"起过又正常退出(status=0)", 属预期不是故障; 需要它时用 `tools/studio_ctl.sh start` 或 `tools/studio_boot_start.sh`(盯 60s 存活) |

## 相关但**不是** systemd 的常驻
- `tools/l2_daemon.py` + `~/zmax_data/l2_cmd.fifo` — L2 收口命令通道(fifo 写入即执行, 见 `zmax-console` / 真机类技能)。
- `tools/auto_loop.py` — 群/网页轮询兜底(WS 断时靠它)。

## 排查顺序 (服务"看起来没起")
1. `systemctl is-enabled/is-active` → 2. `journalctl -u X -n 30` 看真原因(203/EXEC=没 chmod; 空日志=缓冲) → 3. `systemctl restart` 手工复跑同一路径 → 4. 看台账/日志有没有新增行 → 5. 才去怀疑业务逻辑本身。

# 系统自检 · 清理 · 性能 — 2026-09-24 06:49~07:05 (静静)

> 全部数字取自本机实测命令输出；清理台账 `reports/disk_cleanup_ledger_20260924_065021.json`。

## 1. 自检结论 (重启后 3 分钟基线)

| 项 | 值 | 判定 |
|---|---|---|
| 系统 | Ubuntu 24.04.4 LTS · 内核 6.17.0-14-generic · 32 逻辑核 | ✅ |
| 时间 | NTP active · System clock synchronized: yes (CST +0800) | ✅ |
| 失败单元 | `systemctl --failed` = 0 loaded units | ✅ |
| 内存 | 31Gi 总 / 7.9Gi 用 / 23Gi 可用 · swap 15Gi 用 0B · swappiness=10 | ✅ |
| 磁盘(清理前) | 274G 用 / 396G (73%) · 余 103G | ✅ (红线 300G) |
| 在役服务 | ss-remote-tap / ss-yolo-bypass / ss-bypass / ss-local-infer 全 active | ✅ |
| 网关 | hermes gateway alive · 飞书 state=connected (99991663 已随重启自愈) | ✅ |
| GPU | RTX 4060 Laptop · P3 · 43°C · 10.7W 空闲 · persistence_mode 已置 Enabled | ✅ |

## 2. 网络连接检查 (实测 RTT / 解析耗时)

| 目标 | 结果 |
|---|---|
| 默认网关 10.163.147.254 (wlp0s20f3) | 0% 丢包 · 3.0 ms |
| 局域网 DNS 10.160.0.68 | 0% 丢包 · 1.7 ms |
| 公网 223.5.5.5 / 1.1.1.1 | 0% 丢包 · 14.8 ms / 1.7 ms |
| 产线工控机 192.168.23.23 (AOI 10082/10083) | **0.9 ms 可达** |
| 直连口 enx00e04c0c32a0 (192.168.23.50/24) | UP |
| WiFi | Corp-Office 5GHz · signal **-42 dBm** · 573.5 Mbit/s (HE-MCS11/NSS2) |
| DNS 缓存清理 | `resolvectl flush-caches` 后解析耗时 0.00~0.02s (清前 github/registry 0.02~0.17s) |

## 3. 清理明细 (合计释放 7.18 GB → 274G ⇒ 267G, 余 110G)

| 项 | 释放 |
|---|---|
| HF 缓存: SmolVLM2-500M 的 `onnx/*` 导出 (12 个变体, 本机代码零引用) | **4.02 GB** |
| ~/.cache/LarkShell (飞书客户端缓存, 客户端未运行) | 929 MB |
| 回收站 (用户已删文件 24 项) | 546 MB |
| pip + uv 缓存 | 438 MB |
| snap 应用缓存 (firefox/snap-store/chromium/thunderbird) | 183 MB |
| 桌面/GL 可再生缓存 (thumbnails/tracker3/mesa/gnome-thumbnailer/gstreamer) | 176 MB |
| apt 缓存 | 135 MB |
| 轮转日志 (syslog.1/kern.log.1/*.gz) + installer 日志 | 126 MB |
| journal 压缩到 150 MB | ~1.1 GB |
| /var/crash | 7 MB |

**保护清单核对(清理后仍在)**: stable-wm-cache 152G · INTACT-JEPA 11G · lerobot-smolvla-lew 36G · zmax_data 15G ·
zmax_ss_remote 5.5G · HF `model.safetensors` 2.03GB + config/tokenizer 完好 · 无断链 (`find -xtype l` 空)。
onnx 可再生: `hf download HuggingFaceTB/SmolVLM2-500M-Video-Instruct --include 'onnx/*'`。

## 4. 性能: 不吹——CPU 调频档实测无收益, 已回滚

三组交错 A/B 实测 (同负载, powersave vs performance 各 3 轮取中位数, 证据 `reports/perf_governor_bench.json`):

| 负载 | powersave | performance | 比 |
|---|---|---|---|
| 2048³ fp32 matmul (带宽瓶颈) 单轮 | 7.9 GFLOPS | 7.1 | 0.90× |
| 2048³ · 8 线程持续 · 交错 3 轮 | 7.5 | 7.6 | 1.013× |
| 384³ 缓存驻留(计算密集) · 交错 3 轮 | 7.87 | 7.85 | 0.997× |

→ 差异全在噪声内 (驱动 intel_pstate, EPP 已是 balance_performance/performance)。
**结论: 本机 CPU 调频档对算力无可测影响; 已把 governor 回滚 powersave、电源档回滚 balanced, 不留无用发热。**

真正落地/确认的 4 项:
1. **GPU persistence_mode → Enabled** (原来每次 CUDA 进程重启都要重新初始化驱动, 训练/推理反复起停时省 1~2s/次)
2. **GNOME 文件索引 tracker-miner-fs-3 → masked** (后台常驻索引器的 CPU/IO 占用归零; 需要时 `systemctl --user unmask --now tracker-miner-fs-3`)
3. **fstrim.timer = enabled/active** 已确认 (NVMe TRIM 定期回收, 保 SSD 写性能)
4. journal 封顶 200M + 缓存清理 (降低后台 I/O 与写放大)

**如实说明**: 本轮没有"魔法性能提升"项; 真正的算力提升要靠 GPU 侧(训练口径)而非系统旋钮。

## 5. 遗留 (需你决定)

- `~/hermes-portable.tar.gz` 893MB + `~/hermes_core_usb_20260822_1609.zip` 489MB (8 月 21/22 的随身镜像归档, 共 1.38GB) — 不是缓存, 是备份件, 未动; 要不要清?
- snapd 自动刷新 (snapd.refresh.timer) 仍在跑, 每次会占少量 IO — 需要的话可改时间窗, 未动。

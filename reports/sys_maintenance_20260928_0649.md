# 系统维护报告 2026-09-28 06:49（工位机）

## ① 自检
```
时间同步      yes (Asia/Shanghai)          failed units  0
内存          (见 free -h, swappiness=10)
磁盘 /        290653MB → 290382MB 已用 (283.6G / 396G, 76%)
CPU          32 核 · governor=powersave (实测无收益, 按技能保持出厂档不动)
GPU          RTX 4060 Laptop · 6% · 674MiB/8188MiB · persistence=Enabled · 49°C
CPU 占用(1秒差分, 非 ps 生命周期均值)
             cam_live_stream 38% · studio/其他 python 5% · vl_safety_fast 4% · avahi 3% · ss_remote_tap 2%
```

## ② DNS（本轮最实在的一笔）
```
解析链        127.0.0.53 → 10.160.0.68 / 10.160.0.67
清前          baidu 26ms · feishu 10ms · github 7ms · npmmirror 92ms · **hf-mirror 665ms** · pypi 2ms
flush-caches  resolvectl flush-caches 已执行
清后(冷)      baidu 4 · feishu 7 · github 7 · npmmirror 4 · **hf-mirror 7** · pypi 4   (ms)
清后(热)      baidu 2 · feishu 6 · github 6 · npmmirror 3 · hf-mirror 8 · pypi 3      (ms)
⇒ 清掉两条长尾: hf-mirror 665→7ms (95×)、npmmirror 92→4ms (23×)
```

## ③ 网络
```
enx00e04c0c32a0  192.168.23.50/24   (产线口, 本来无网关)
wlp0s20f3        10.163.146.78/23   (办公 WiFi)
网关 10.163.147.254   1.98ms   0% 丢包
223.5.5.5            13.99ms   1.1.1.1  1.73ms
现场 Orin 192.168.23.66  0.191ms  ← 极好
现场 工控机 192.168.23.23 1.145ms
WAN 实速(阿里云镜像 3 次)  1.56 / 1.56 MB/s  ⇒ ≈12.5 Mbps (办公网出口限制, 非本机问题)
TCP 旋钮(逐项核在效)  bbr · fq · rmem_max 32M · wmem_max 16M · fastopen=3 · tw_reuse=2
                      slow_start_after_idle=0 · mtu_probing=1
⇒ 网络旋钮已是最优档, 无可再加的"魔法加速"; 要提速只能改出口带宽
```

## ④ 缓存清理明细（只动可再生的）
```
日志轮转 1MB · crash 转储 1MB · apt 包缓存 1MB · **apt 列表 272MB** · pip/uv/thumbnails/
tracker3/mesa/gnome-thumb 各 1MB · 回收站 0MB · journal 193.5M(已在 200M 封顶内, 无可回收)
────────────────────────────────────────────
合计净释放 271MB (290653 → 290382MB)
```
**如实说明**：系统层缓存本来就只有 ~280MB 量级可清（与技能记载一致）。
真正占盘的是**训练缓存**（`~/stable-wm-cache` ≈151G，其中单个 h5 95G，被 INTACT-JEPA 训练配置引用
= 在用数据），**属保护清单，只列不删**。要腾出几十 G 必须你点头。

## ⑤ 性能项（都实测在位）
```
GPU persistence        Enabled  (反复起停 CUDA 省驱动重初始化)
tracker-miner-fs-3     inactive (masked) —— 关掉桌面索引器
fstrim.timer           active · 本轮 fstrim -v / = **10.3 GiB trimmed** (NVMe TRIM)
journal 封顶           200M
```
未做/已回滚：CPU governor 调到 performance —— 技能里实测 3 组交错 A/B 全在噪声内（带宽瓶颈负载
不适合测频率），**无收益 ⇒ 不留表演性设置**。

## ⑥ 保护清单复核
未触碰：`~/stable-wm-cache`(训练数据/ckpt) · 在役仓库 · 在役权重(`yolo_peg_live.pt` 软链及其指向) ·
`~/zmax_data`(真机原始数据/标定/台账) · 8791 推流服务(在役链路, 只清理不动服务)

## ⑦ 遗留待决
1. 训练缓存 151G —— 要不要清理/迁移，等你点头（涉及在用训练数据）。
2. WAN 出口 12.5Mbps 是办公网限制，本机侧已无可优化项。
3. 下次建议：把 `/tmp/sys_clean_v2.sh` 收进 `tools/`（当前在 /tmp，重启即失）。

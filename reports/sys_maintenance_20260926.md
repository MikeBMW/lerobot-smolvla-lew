# 工位机 系统清理 / DNS / 网络体检 — 2026-09-26 08:0x (静静)

> 依据 skill `linux-host-maintenance`(§0铁律/§4矩阵/§6性能) + `linux-network-perf-boot`(§3测法)。只删可再生, 保护清单逐条核对。

## 一、清理 (每项前→后, 台账 reports/sys_cleanup_20260926_080719.json)
```
journal→200M          438MB →  151MB   释放 287MB
apt 列表缓存          272MB →    1MB   释放 271MB
uv 缓存               255MB →    1MB   释放 254MB
pip 缓存               12MB →    1MB   释放  11MB
日志轮转              320MB →  315MB   释放   5MB
chromium 缓存           5MB →    1MB   释放   4MB
mesa 着色器             4MB →    1MB   释放   3MB
崩溃转储/缩略图/tracker3/回收站/snap  已清 (≈0)
---------------------------------------------------
合计释放 835MB · 系统盘 used 298153→297528MB (df 291G/300G 红线, 可用 86G)
```
HF 缓存 2252MB 已无 onnx 冗余(早前已瘦身)· 断链检查 0 个 · .incomplete 已清

## 二、效率项 (skill §6 四项全部落地)
```
GPU persistence_mode  Disabled → Enabled   (反复起停 CUDA 省驱动重初始化)
fstrim.timer          enabled+active       (实测本轮 TRIM 105.3 GiB)
tracker-miner-fs-3    masked/inactive      (停后台文件索引扫描)
journal 封顶 200M      ✅ (本轮 438→151MB)
```

## 三、DNS
```
解析链: 127.0.0.53 → 10.160.0.68 (局域网 DNS)
flush-caches 后 5 域冷解析: 0.00~0.03s; 预热后热解析 5/5 = 0.00s
```

## 四、网络: 旋钮实测生效 + 延迟/带宽复核
```
net.core.rmem_max                          33554432
net.core.wmem_max                          16777216
net.ipv4.tcp_slow_start_after_idle         0
net.ipv4.tcp_congestion_control            bbr
net.core.default_qdisc                     fq
net.ipv4.tcp_fastopen                      3
net.core.netdev_max_backlog                5000
net.core.somaxconn                         8192
WiFi(wlp0s20f3) power_save=off · -42dBm · 573.5Mbit/s (40MHz HE-MCS11/NSS2)
远端单流下载 3 轮: 4.27 / 4.49 / 5.36 MB/s → 中位 4.49 MB/s (基线中位 4.30, 优化后曾测 5.12)
TTFB(npmmirror 中位) 0.099s
```
判读: 旋钮全部在效; 今日中位 4.49MB/s 与基线 4.30/昨日 5.12 落在同一噪声带 (WiFi+CDN 抖动 ±30% 级), 不重复声明增益。

## 五、本轮新做的 A/B (拒绝 cargo-cult)
```
① tcp_tw_reuse: 0(关) 1429ms vs 1(开) 1376ms → 关掉慢 3.7%, 3/3 轮一致 → 结论: reuse 必须保持开启
② 严谨对消 1 vs 2(出厂值): 1344ms vs 1370ms → 差 1.9% 落在噪声内 → **不改**, 保持出厂 2
   (实测本机 9Hz 短连接产生 631 条 TIME_WAIT; 要真的降只能客户端复用连接 = 应用层改动, 未做)
```

## 六、保护清单复核 (清理后)
```
/home/ubuntu/zmax_ss_remote                    在
/home/ubuntu/stable-wm-cache                   在
/home/ubuntu/zmax_rel                          在
/home/ubuntu/zmax_data                         在
/home/ubuntu/zmax_dds                          在
/home/ubuntu/lerobot-smolvla-lew/models        在
在役服务 11/11 active (ss-local-infer/ss-bypass/ss-remote-tap/ss-yolo-bypass/zmax-net-optimize/
  zmax-web-agent-bridge/aoi-feishu-push/zmax-dds-ss/zmax-dds-pub/zmax-dds-agg/zmax-data-mount)
```

## 七、剩余磁盘大头 (未动, 需你点头)
```
stable-wm-cache  164G  受保护 (在役权重+数据集; disk_redline dry-run 判'在红线内'故未清)
zmax_ss_remote   7.6G  真机采集原始 jsonl (训练数据, 非缓存)
lerobot-smolvla-lew(mac-hw 检出) 37G  并行 APP 线的工作目录
zmax_data        13G  历史归档 (5.13.x~5.15.7 release_*)
```

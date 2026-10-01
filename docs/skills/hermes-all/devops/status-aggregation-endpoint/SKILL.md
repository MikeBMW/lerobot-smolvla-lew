---
name: status-aggregation-endpoint
description: Use when 状态要聚合成只读 JSON 端点挂到已有服务端口.
version: 1.0.0
author: Hermes
license: MIT
metadata:
  hermes:
    tags: [status, json-endpoint, systemd, degradation, regression]
    related_skills: [user-facing-dashboard-delivery, systemd-boot-services, shared-state-file-integrity]
---

# 状态聚合端点 (挂在已被占用的端口上)

## When to Use

- 用户要「看状态」: GPU/CPU/内存/磁盘 + 在役模型版本 + 是否在推理/训练 + 3DGS 资产版本。
- 要往一个**已被 systemd 服务独占的端口**加只读路由 (不抢端口, 不新起服务)。
- 已有大屏/面板需要固定 JSON 契约的只读状态源。

适用: 用户要「看状态」(GPU/CPU/内存/磁盘 + 在役模型版本 + 是否在推理/训练 + 3DGS 资产版本),
或要往一个已被 systemd 服务独占的端口加只读路由。

## 铁律

1. **不抢端口**: 端口已被服务占用(如 8796=sam3-seg / 8790=ss-local-infer)时, 在该服务的 HTTP handler 里
   **新增一个 GET 路由**, 聚合逻辑写进独立模块。服务主体保持干净, `/health` 与业务路由一行不动。
2. **后台线程刷缓存, 请求只读快照**: 采集放 daemon 线程每 1s 跑; handler 只返回缓存 ⇒ 响应 ~0.5ms。
   冷启动时首个请求会退化到同步全量采集(几十 ms) ⇒ 在 `serve_forever()` **之前预热一次**。
3. **降级到字段级, 不降级到状态码**: 每段采集包 try/except, 失败给 `null`/`0`/`[]` + `"err"`,
   外层再兜一层「全降级契约」。**新路由永不 500**, 宁可返回带 err 的 200。
4. **契约先写死再实现**: 字段名/层级由下游 GUI 定死, 一个字不许改; 额外信息只进 `err`/`note`。
5. **版本真源单独落盘** (如 `models_manifest.json`), 结构 `{"L2":[...],"L4":[...]}`,
   每条带 `version`/`state`/`artifact` + `probe`。**不确定的一律 `unknown`, 不编**。
6. **inferring 必须是真探针**, 不是猜测:
   - `http_counter`: 读别的服务 `/health` 的 `infer_count` 看是否增长;
   - `file_fresh`: 产物/心跳文件 mtime 新鲜度;
   - `json_counter`: 状态 json 里的计数;
   - `http_ts`/`json_age`: 指向「最近一次调用时刻」或 DDS `age_s`。
   无探针 ⇒ `inferring=false` 并在 note 里写明「无该层计数, 如实标注」。
   代理信号(引擎节拍当某层推理证据)**必须**在 note 里标明是代理。
7. **计数器探针用窗口比较, 不用相邻两跳**: 被监控文件可能 5s 才重写一次, 1s 窗口会漏成 false。
   维护 `{key: [(ts,val),...]}` 历史, 跟「窗口前最早的样本」比。
8. **训练检测**: `nvidia-smi --query-compute-apps=pid,used_memory` 里显存 > 阈值(1500MiB) ⇒ 候选;
   读 `/proc/<pid>/cmdline` 分类层级; 进度从**最新真实日志**尾部解析。系统里常见四种口径:
   - lerobot: `Training: 98%|…| 197/200 [08:34<00:07, 2.58s/step]` + `step:200 … updt_s:2.571`
   - INTACT: `[Epoch 0/1] step 150/200 (1.5 it/s)` (速度 = 1/it_s)
   - ultralytics: `      29/30      1.28G …` (epoch 粒度, 前面可能有 `\r\x1b[K`, 正则要放宽前导)
   - jsonl 微调: `{"step":540,…,"s_per_step":0.67}`, total 从产物 `run_report.json` 的 `steps` 补
   训练不在跑时, **拿历史真日志验证解析器**(step/total 应等于日志尾行), 这是合法取证, 别造数据。
9. **资产版本号**: 用 `sha1(目录名 + 训练配置关键字段 + 文件 size/mtime)` 取前 8 位 +
   `v<日期>-<短哈希>`。内容不变版本不变; 只把「真产出」(如 `gs.ply`+`train_report.json`)算资产。

## 回归 (改完占用端口的服务必做)

```
sudo systemctl restart <svc> && sleep 4
systemctl is-active <svc>; journalctl -u <svc> -n 5 --no-pager
curl -s http://127.0.0.1:PORT/health          # 老路由
curl -s -w ' [%{http_code} %{time_total}s]' http://127.0.0.1:PORT/status/all
# 业务路由: 用**与历史同口径**的输入复跑(同一相机源 + 同一组提示词), 对得上数量才算过
```

同口径复跑是唯一可信的业务回归: 换一张图/换一组提示词拿到 0 结果, 说明不了是改动还是输入问题。

## 收尾

- 自检脚本要覆盖: 契约类型、缺 manifest、命令不可用、目录不可达、坏探针 URL、采集被强制打崩。
- 演练用「真实记录喂入 + 真实日志解析」, 明确标注哪部分是接线演练。
- 验证完把占用卡/显存的服务**重启回 lazy 态**, 别留资源占用。
- 提交只 add 自己的文件 (仓库常有多 agent 未提交改动)。

# 「本机聚合端点 → 公网镜像 → 他手机那个页面」双跳链

用户要的“看板/版本号/硬件状态”几乎总是要看在**手机上的某个公网 URL**，而不是本机端口。
本文件是这条链的现成做法（Z-MAX 工位机实测），照着接就不必重踩“只做了本机那一半”。

## 1. 冻结契约（先说好，再并行做两头）
`GET http://127.0.0.1:<本机端口>/status/all` —— **只增不改**；消费端（页面）按此解析：
```json
{"ts": 0.0,
 "hw": {"gpu":{"util":0,"mem_used_mb":0,"mem_total_mb":0,"temp_c":0,"name":""},
        "cpu":{"util":0,"cores":0,"load1":0.0},
        "mem":{"used_gb":0.0,"total_gb":0.0},
        "disk":{"used_gb":0,"total_gb":0,"pct":0}},
 "models": [{"layer":"L2|L3|L4|L5","name":"","version":"",
             "state":"in_service|candidate|untrained|unknown","inferring":false}],
 "training": {"active":false,"layer":"","name":"","version":"",
              "step":0,"total":0,"pct":0,"eta_s":0,"speed_s_per_step":0.0},
 "assets": [{"kind":"3DGS","name":"","version":"","path":""}]}
```
- **版本号真源 = 一个 manifest 文件**（如 `src/lerobot/engineering/models_manifest.json`），
  不要散在代码里；每条带 `artifact` 绝对路径 + `state` + `probe`（怎么判它在推理）。
- 没证据的条目写 `"unknown"` + 在 manifest 的 note 里写"无版本证据"。**宁缺毋编** ——
  用户会拿这张表逐个检查，编一个就等于整张表作废。
- 采样：`nvidia-smi --query-gpu=... --format=csv,noheader` · `/proc/stat`+`/proc/loadavg`+`/proc/meminfo` ·
  `shutil.disk_usage('/')` · 训练中 = `--query-compute-apps=pid,used_memory` 里 **>1500MiB** 的进程。
- **必须后台 1s 刷快照、请求只读缓存** ⇒ 实测响应 <1ms（每次全量采集会把页面拖慢）。
- **每段独立降级**（给 `null`/0 + 一个 `err` 字段），最外层兜底契约 ⇒ 任何一个采样器崩了也不能 500。

## 2. 往本机服务加路由时不要抢端口
目标服务常已被别的服务占着（如 SAM3 的 `--serve --port 8796`）：
**在它的 `do_GET` 里加一条只读路由**，聚合逻辑放进独立模块（保持服务主体干净），改完
`systemctl restart` 并**回归原功能**（`/health`、`/seg` 各 curl 一次贴输出）。
若文件里能改出 `do_HEAD`（转 `do_GET` 但不写 body）就补上 ⇒ `curl -I` 才可用。

## 3. 发到公网（手机真正读的那一跳）
- 站根推送通道：`POST https://<站>/ss3d_push.php?token=<tok>&f=<文件名>`，body = 文件内容。
- 服务端 **文件名白名单**：扩表只**只加不改**（原两条保留 + `fnmatch` glob），改前
  `cp ss3d_push.php ss3d_push.php.bak_<ts>`，改完远端 `php -l`。
- 推送器要可 cron：`--if-changed`（md5/指纹未变就跳），别对外网做无意义写入。
- 状态类要**新鲜** ⇒ 每分钟级 cron（不是小时级）；分版本留档的产物（如画布 PDF）小时级即可。
- **公网页与局域网页是两份产物**：要么同源同文件，要么写清真源 + 同步器；
  否则你会改一边、用户看另一边。

## 4. 页面那条状态带（用户口径）
- 形态：**极小面积**。第一行 `GPU/CPU/内存/磁盘` 四条迷你条 + 3~4 字数字 + Ø8px 红绿灯；
  第二行每模型 `圆点 + 层标 + 极短版本号` + 训练进度条 + `%` + 末尾 `3DGS v…`。
- 颜色语义统一：**绿=在役健康 · 黄=候选/忙 · 红=异常或未训练 · 灰=未知**。
- 数据源必须读**公网 URL**（`fetch` 自己 origin 或公网 JSON），**绝不能用 `127.0.0.1`**。
- 轮询 5s，读失败**整体变灰静默降级**（弹窗/报错/卡 UI 都不合格）；值不变不重绘。
- 手机竖屏（375~430px）验收：**不横向滚动、不截断**；拿不到真浏览器就老实说，别用 curl 冒充截图。

## 5. 验收（每一条都要自己跑，不采信子代理/发布器自述）
```bash
ss -ltn | grep <端口>                                  # ① 看监听地址: 127.0.0.1 还是 0.0.0.0
curl -s http://127.0.0.1:<端口>/status/all | head -c 300  # ② 本机契约
curl -sI https://<站>/<公网 JSON>                    # ③ 公网 200 + 类型 + 长度
curl -s https://<站>/<公网 JSON> | head -c 300       # ④ 内容新鲜度(看 ts 与 training)
curl -s "https://<站>/<他那个页面>?k=…&v=$(date +%s)" | grep -c <状态条容器 id>   # ⑤ 页面已接上
```
- 他报"还是看不到"时，先把 **`training.active` / 数据龄 / 页面字节数** 三样拿出来，再给**破缓存链接**；
  排除掉"没活干"与"浏览器缓存"之后，剩下的才是真 bug。

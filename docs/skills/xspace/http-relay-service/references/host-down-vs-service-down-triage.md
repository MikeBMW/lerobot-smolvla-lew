# 整站不可达: 实例停机 vs web 层死 —— 取证命令与判据

实测日期 2026-09-20 (Z-MAX: datadrive.world / ECS 39.102.211.79). 场景: 用户回到工位说"元气恢复",
例行体检发现巡检连续报 `relay/orin/snapshot` 全 FAIL, 端侧 WS 一直重连. 结论: **ECS 实例级不可达**,
本机无法修. 本文只记"怎么在 5 分钟内定性", 不承诺修复路径 (需要云控制台).

## 判据表

| 观测 | 含义 | 下一步 |
|---|---|---|
| 本机 curl 百度/GitHub 200 | 本地上行正常 | 继续 |
| `getent hosts <domain>` 有 IP, curl `conn=0.000000` + timeout | DNS 正常, TCP 建不起来 | 查端口面 |
| `/dev/tcp/<ip>/{22,80,443}` 全 filtered | 不是安全组只挡高端口 (443 是 relay 入口) | 外部多节点取证 |
| check-host `check-tcp` 5 节点全 `Connection timed out` | **实例级不可达** (停机/IP 漂移/网络黑洞) | 交云控制台; 本机别折腾 |
| check-host `check-ping` 返回 `None` | 阿里云丢 ICMP, **不作为判据** | 看 TCP 结果 |
| 第三方 HTTP 代理 522/超时 | 旁证源站不可达 | 一并写进结论 |
| 主机 ping/22 通, 只有 443/relay 端点红 | web 层 (nginx/relay) 死 | 走 SKILL §9 宝塔双 nginx 阶梯 |

## 可直接复用的命令

```bash
# 1) 本机上行基线
for u in https://www.baidu.com https://api.github.com; do
  printf '%s -> ' "$u"; curl -sS -o /dev/null -w '%{http_code}\n' --max-time 10 "$u"; done

# 2) DNS 与 TCP 分相 (conn=0.000000 = 没建连)
getent hosts <domain>
curl -sS -o /dev/null -w 'code=%{http_code} dns=%{time_namelookup} conn=%{time_connect} total=%{time_total}\n' \
     --max-time 12 https://<domain>/api/relay/status

# 3) 端口面
for p in 22 80 443; do timeout 5 bash -c "cat < /dev/null > /dev/tcp/<ip>/$p" 2>/dev/null \
  && echo "$p open" || echo "$p closed/filtered"; done

# 4) 外部多节点 TCP 取证 (request_id → 轮询)
rid=$(curl -sS -H 'Accept: application/json' \
  "https://check-host.net/check-tcp?host=<ip>:443&max_nodes=5" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["request_id"])')
sleep 25
curl -sS -H 'Accept: application/json' "https://check-host.net/check-result/$rid"
# 可用节点示例: ch2/de4/es1/jp1/ua1/br1/il2/pl2/vn1.node.check-host.net
# 期望形态: {"br1...": [{"error": "Connection timed out"}], ...}

# 5) 第三方代理旁证 (代理自身网络正常 → 522 即源站不可达)
curl -sS --max-time 25 "https://api.codetabs.com/v1/proxy?quest=https://<domain>/api/relay/status"
```

## 停机时长的取证 (不要编精确起点)

- 每次巡检的报告落在 `~/.hermes/cron/output/<job_id>/YYYY-MM-DD_HH-MM-SS.md` (只保留最近 N 份).
- 用 `grep -l 链路正常 *` / `grep -l 链路异常 *` 找**边界**: 边界被轮转掉时, 只能说
  "**至少自 <保留期内最早那一条> 起就是异常**" —— 实测保留 50 份时只能回溯到昨天早上.
- 别用 `ls -t` 第一条当起点, 也别拿日志里的相对时间当绝对时间 (本机有 NTP 回拨史, 见
  `unattended-pipeline-supervision` 的时钟坑).

## 影响面 (报给用户时别只说"网站挂了")

同一台 ECS 承载: 网站/控制台前端 · relay 上传下载队列 · Orin 心跳与快照 API · WS 事件 hub.
实例一死 → 网站打不开 + 群消息断 + 中转停 + Orin "不在线" + 端侧 WS 无限重连转轮询兜底.
**本地侧不受影响**: 采集进程/边缘 tap/本地推理/L2 常驻执行器照跑 (只在要 publish 的那一刻才断) ——
报现状要明确区分这一点, 否则用户会以为整条链路停摆.

## 本机做不到什么 (老实说)

- 无阿里云 CLI 凭据 → 不能查/启停实例.
- 22 端口也死 → 拿不到 shell, 修不了 nginx/relay.
- 因此结论应是: "需要云账号持有人去控制台看实例状态 (并核对公网 IP 是否漂移, 漂了要改 DNS A 记录)",
  不要写成"已尝试修复"或给出没验证过的修复步骤.

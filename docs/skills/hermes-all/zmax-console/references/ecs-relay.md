# ECS 中转服务 + Simulink 验证 CI — 实战细节 (2026-08-01)

## 架构链路
```
Orin(192.168.23.10:8765 采集) → Mac(192.168.23.1:8769 中转) → ECS中转(datadrive.world/api/relay)
  → 4060本地(relay_train.py pull→npz→ACT训练) → ECS(上传模型) → Mac(cicd_pull_deploy.py) → Orin部署
```
数据方向 (老倪 2026-08-01 指令): 采集10秒 → Mac中转 → ECS中转 → 4060本地训练 ACT → 部署 Orin。

## ECS 中转服务 (zmax_relay.py)
位置: `/root/zmax-relay/zmax_relay.py`, 数据目录 `/root/zmax-relay/data/`, 端口 **39053** (nginx 反代目标)。
启动: `bash /root/zmax-relay/start.sh`。验证: `curl -s https://datadrive.world/api/relay/status`。

端点:
| 端点 | 方法 | 说明 |
|---|---|---|
| `/upload` | POST | json (`name`/`meta`/`frames`/`data`) 或原始字节 (npz/模型).json 存 `data/`, npz 直接写文件 |
| `/latest` | GET | 拉最新包, **弹栈式: 拉取即删** (中转不留存) |
| `/peek` | GET | 🆕 **只读不删**: 查看队头 — json 返回内容+`_peek` 元信息, 二进制只返回 `{binary,size,mtime,hint}` 不传内容 |
| `/status` | GET | packages 数 / latest / uptime |
| `/packages` | GET | 包列表 (glob `*` 含二进制) |
| `/ci/validate` | POST | Simulink 模型验证, body=flow json, 返回 `{"ok":true,"ci":{checks...}}` |

约束: 缓冲总量 ≤100M (enforce_buf_limit 超限删最旧); 拉取即删。

## ⚠️ 弹栈式队列的坑 (2026-08-02 实战事故)
`/latest` 取走即删 — 第一次 GET 把 87MB 二进制弹出且未保存, 队列直接空。教训:
- 消费前先 `/peek` 确认 (看 size/二进制名), 确认是目标再 `/latest` 取。
- 二进制模型拉取必须用 `cicd_pull_deploy.py` (requests .content 写文件) 或 `curl -o file`; `relay_train.py pull` 只用于 JSON 训练数据 (r.json()), 别混用。
- 弹栈即删也意味着测试时别随手 GET /latest 消费真实队列。

## ⚠️ 大文件上传 OOM 崩溃 + 流式修复 (2026-08-02)
ECS 仅 3.5GB 内存。旧 `/upload` 整包 `self.rfile.read(length)` + `json.loads(raw)` 处理 84MB safetensors → 进程被杀 (日志戛然而止, 无 Traceback; dmesg 无 OOM 记录因无权限)。修: 流式分块写盘 (16KB/64KB chunks, 不整包进内存)。

**JSON vs 二进制判定坑**: safetensors 文件头本身就是合法 JSON (以 `{` 开头)! 只判前缀 `startswith("{")` 会把模型误判成 JSON 包 → UnicodeDecodeError。正确: 读前 4KB → `json.loads(head)` 完整解析成功才算 JSON 包, 否则走二进制流式分支。

**nginx 超时坑**: 默认 proxy 超时 60s, 84MB 慢速上传被掐断 → 502 (relay 日志无记录)。须加长:
```
location /api/relay/ {
    client_max_body_size 200m;
    proxy_pass http://127.0.0.1:39053/;
    proxy_read_timeout 300s; proxy_send_timeout 300s; proxy_connect_timeout 30s; }
```

## nginx 反代配置 (绕过阿里云安全组)
`/www/server/panel/vhost/nginx/datadrive.world.conf` (已备份 .bak):
```
location /api/relay/ { client_max_body_size 200m; proxy_pass http://127.0.0.1:39053/; }
```
- 安全组只放行 80/443 等常见端口; 50053/39053 公网直连全超时 (ufw 放行无效, 安全组在外层)。
- 修改后: `nginx -t && /etc/init.d/nginx reload` (宝塔环境用 init.d, systemctl 不生效: "nginx.service is not active")。
- **端口不一致 → 502**: scp 覆盖 relay 脚本后检查 `grep -n 'port = ' zmax_relay.py` (必须 39053), 否则 502。

## Simulink 模型验证 CI (simulink_ci.py)
位置: `tools/gui/simulink_ci.py` (本地 + ECS `/root/zmax-relay/simulink_ci.py` 双部署)。

8 项检查: format / version / 节点Schema(5类枚举+必填键+重复id) / 连线引用 / 拓扑DAG无环 / 端口匹配(f_port/t_port 存在) / 参数类型 / 仿真执行(10步×拓扑序, 检测运行时错误)。

用法:
```bash
python3 tools/gui/simulink_ci.py test        # 内置回归: 合法PASS+非法FAIL, exit code 可断言
python3 tools/gui/simulink_ci.py validate flow.json [--report r.html]
python3 tools/gui/simulink_ci.py pipeline flow.json --report r.html [--upload]
```
CI 报告工件: JSON (to_json) + HTML (to_html, 深色 GitHub 风格, PASS/FAIL 徽章)。

ECS 端点实现要点 (`/ci/validate`): 直接 `import sys as _sys; _sys.path.insert(0, '/root/zmax-relay'); from simulink_ci import run_checks` — **不要用 subprocess.run + input=bytes + text=True** (会报 `'bytes' object has no attribute 'encode'`); `sys` 未导入也要注意 (用 `import sys as _sys`)。

GitHub Actions: `.github/workflows/simulink-ci.yml` — push 触发 (simulink-spec.md / tools/gui/simulink_*.py / flow*.json), 跑回归 + 仓库内所有 flow 验证 + 上传报告工件。

web 端 comfyui mock (`/api/comfy/task`, 127.0.0.1:50058): `detect_model()` 原本只吃字符串列表, simulink 规范传 dict 节点 → 需兼容补丁 (nodes[0] 是 dict 时取 `n.get("name")`)。mock 常挂 → `bash /root/zmax-website/start_comfy.sh` 重启。

## 数据包格式约定
```json
{"name": "pkg_xxx.json", "meta": {"frames": N, ...}, "frames": [
  {"index": i, "timestamp": ..., "observation.state": [7维], "action": [6维], "camera_b64": "...", "force_torque": [...]}
]}
```
relay_train.py to_lerobot: states/actions 取前 N 维, camera_b64 → cv2 resize 64x64 → (3,64,64)。

## 实测结果
- 上传→拉取→删除→404 全通 (缓冲零残留)。
- GUI simulink 集成: 首页卡片 / modules dict (simulink:11) / stack 挂载 / flow_synced→on_flow_sync POST `/api/comfy/task` / `_on_nav` names 列表 12 项 (漏加 IndexError)。
- CI 验证 8/8 PASS (demo_flow: Orin→ACT→力控插入)。

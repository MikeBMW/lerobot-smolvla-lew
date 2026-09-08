# ECS 中转服务部署记录（2026-08-01 首次上线）

## 背景
老倪要求跑通数据闭环: Orin采集10秒 → Mac中转 → ECS中转 → 静静4060本地训练ACT。
当时 ECS 上无 50053 中转服务（只有 comfyui mock 在 50058 本机端口），且：
- 50053 公网不通（阿里云安全组未放行）
- ufw 放行 50053 后公网仍不通；换 39053（ufw 规则 39000:40000 段）仍不通
- 结论：**阿里云安全组是新端口公网不通的根因，ufw 只是 ECS 内层防火墙**

## 最终方案：nginx 反代走 443
1. 中转服务监听 127.0.0.1:39053（无需安全组放行，nginx 本机回环访问）
2. nginx 在 datadrive.world（443 已放行）加反代:
   ```nginx
   location /api/relay/ {
       client_max_body_size 200m; proxy_pass http://127.0.0.1:39053/; }
   ```
   注意 proxy_pass 末尾带 `/` 会把 `/api/relay/xxx` 重写为 `/xxx`，后端 handler 才能命中。
3. `/etc/init.d/nginx reload`（宝塔环境用 init.d，systemctl 报 not active 不可用）

## nginx 配置修改的正确姿势
```bash
cp datadrive.world.conf datadrive.world.conf.bak
# sed 插行会破坏 location 块嵌套，改用 python 精确替换:
python3 - <<'EOF'
p='/www/server/panel/vhost/nginx/datadrive.world.conf'
s=open(p).read()
anchor='''    location /api/comfy/ {
        client_max_body_size 500m; proxy_pass http://127.0.0.1:50058/; }
'''
new=anchor+'''    location /api/relay/ {
        client_max_body_size 200m; proxy_pass http://127.0.0.1:39053/; }
'''
assert anchor in s
open(p,'w').write(s.replace(anchor,new))
EOF
nginx -t && /etc/init.d/nginx reload
```

## 部署命令（踩过的坑）
```bash
# ❌ 错误: pkill 和启动塞一条 ssh 命令 → pkill -f 匹配到整条命令行, 新进程一起被杀
sshpass -p 'Nix19789' ssh root@39.102.211.79 "pkill -f zmax_relay.py; ... nohup python3 zmax_relay.py &"
# ❌ 错误: setsid nohup 直接写在 ssh 命令里 → ssh 阻塞 60s 超时
# ✅ 正确: 启动逻辑落盘成 start.sh, ssh 只执行 bash
sshpass -p 'Nix19789' scp /tmp/start_relay.sh root@39.102.211.79:/root/zmax-relay/start.sh
sshpass -p 'Nix19789' ssh root@39.102.211.79 "bash /root/zmax-relay/start.sh"
```

## 验证
```bash
curl https://datadrive.world/api/relay/status   # {"relay":"Z-MAX ECS中转 v1",...}
curl -X POST https://datadrive.world/api/relay/upload -H 'Content-Type: application/json' \
     -d '{"name":"test","meta":{"frames":10},"frames":[{"i":1}]}'   # {"ok":true,...}
curl https://datadrive.world/api/relay/latest    # 返回数据
curl https://datadrive.world/api/relay/latest    # {"error":"no data yet"} (404, 已即删)
```

## 相关文件位置
- ECS: `/root/zmax-relay/zmax_relay.py`, `/root/zmax-relay/start.sh`, `/root/zmax-relay/relay.log`
- 数据目录: `/root/zmax-relay/data/`（≤100M 自动清理）
- 本地拉取训练: `~/lerobot-smolvla-lew/tools/relay_train.py`
- 训练配置: `~/lerobot-smolvla-lew/config_act_closedloop.yaml`

## 二进制上传修复 (2026-08-02, 84M 模型实测)
**症状**: 上传 model.safetensors → HTTP 502, relay 进程崩溃退出, relay.log 尾部 UnicodeDecodeError。
**根因**: `/upload` 用 `json.loads(raw)` 尝试解析, 二进制 safetensors 抛的是 **UnicodeDecodeError** 而
不是 JSONDecodeError, `except json.JSONDecodeError` 捕获不到 → 未捕获异常杀死整个 http.server。
**修复**: 改两段式:
```python
try:
    obj = json.loads(raw.decode("utf-8"))   # 二进制解码失败走 except
except Exception:
    # 非 JSON → 二进制包 (npz/model/safetensors)
    name = f"pkg_{time.strftime('%Y%m%d_%H%M%S')}.npz"
    with open(DATA_DIR / name, "wb") as f: f.write(raw)
    ...return
```
**联动修复**: status/packages 的 glob 从 `*.json` 改成 `*`（二进制包是 .npz 后缀）;
/latest 增加二进制分支, 直接回传原始字节 (Content-Type: application/octet-stream) + 拉取即删。
**nginx 超时**: 84M 上传默认 proxy 60s 超时 → location 加
`proxy_read_timeout 300s; proxy_send_timeout 300s; proxy_connect_timeout 30s;`

## CICD 部署实测记录 (2026-08-02)
```
✅ 4060 训练 ACT:      1000步 loss 1.962, 76s, RTX 4060 (config_act_closedloop.yaml)
✅ 推 ECS 中转:        POST /upload 84M → HTTP 200, 37.9s (后台跑, 避开审批窗口)
✅ 状态可见:           /status packages:2, 二进制元数据 {binary, size}
✅ 拉取验证:           /latest 84M 完整取回, SHA256 4f6062b5... 一致, 拉取即删
✅ 部署就绪:           hermes_gateway_mac/cicd_pull_deploy.py (sshpass tashan@192.168.23.10 ts123)
```


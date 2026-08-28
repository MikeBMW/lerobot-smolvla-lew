# ECS relay 快照 502 / cicd.html 无图像 排查实录 (2026-08-06)

> 老倪报障: "https://datadrive.world/cicd.html 没有图像"。完整根因链 + 修复，未来同类报障直接照此排查。

## 症状
- `https://datadrive.world/api/snapshot/latest` → 502 Bad Gateway / 连接重置 (本地 curl 报 HTTP 000)
- cicd.html 实时画面空白
- **注意**: `/api/relay/orin/status` 仍 200 正常 — 症状分化是关键线索

## 根因链
```
archive 目录每秒写 1 张快照 (Orin 推流) → 累积 1170 万个文件 (1.7GB, 目录项 11710464)
→ relay 的 glob("/root/zmax-relay/archive/snap_*.jpg") 全目录扫描卡死
→ /api/snapshot/latest 端点超时 → nginx 502 → cicd.html 图像空白
```

## 排查步骤 (按序)
1. `curl -s -m 8 https://datadrive.world/api/relay/cam/status` → 502 (先确认全链路还是单端点)
2. `curl -s https://datadrive.world/api/relay/orin/status` → 200 → **不是 relay 整体挂**
3. `sshpass -p 'Nix19789' ssh root@39.102.211.79 "ps aux | grep zmax_relay | grep -v grep | wc -l; ss -tln | grep 39053"` → 进程在
4. ECS 本机 `curl http://127.0.0.1:39053/api/snapshot/latest` → 也 000 → 端点内部阻塞 (非网络)
5. `ls /root/zmax-relay/archive | wc -l` → 1170 万 → 实锤 glob 卡死

## 修复三件套 (已进 zmax_relay.py + guard.sh)
```python
# ① glob 全扫 → os.listdir + 后缀过滤 (只读最新, 不扫全目录)
arch = sorted(f"/root/zmax-relay/archive/{f}" for f in os.listdir("/root/zmax-relay/archive") if f.endswith(".jpg"))

# ② 归档上限 300: 写快照后清旧 (防再累积)
_jf = sorted(arch_dir.glob('snap_*.jpg'))
for _old in _jf[:-300]:
    try: _old.unlink()
    except Exception: pass
```
```bash
# ③ relay 守护进程 guard.sh (nohup 后台, 每 60s 检查, 挂了自动拉起)
while true; do
  if ! ss -tln | grep -q 39053; then
    echo "$(date '+%H:%M:%S') relay 挂了, 自动拉起" >> /root/zmax-relay/guard.log
    cd /root/zmax-relay && bash start.sh > /dev/null 2>&1
  fi
  sleep 60
done
```
清理存量: `cd /root/zmax-relay/archive && ls -t | tail -n +100 | xargs -r rm -f` (1170万→109个, 1.7GB→13MB)

## 验证
- ECS 本机: `curl http://127.0.0.1:39053/api/snapshot/latest` → 200 + ~11KB
- 公网: `curl -o /tmp/s.jpg https://datadrive.world/api/snapshot/latest; file /tmp/s.jpg` → JPEG image data 480x360
- 快照文件本身有效 (JPEG 头 ffd8ffe0, 11KB) — 之前误以为"图像没推", 实际是端点读不出来

## 通用教训
- **HTTP 000/502 症状分化排查**: 一个端点挂 vs 全部挂 → 先用相邻端点 (orin/status) 区分 relay 进程死 vs 单端点逻辑卡
- **archive/日志类目录必须设上限** — 每秒写入的目录, 无上限就是定时炸弹 (千万级文件后任何 glob/find 都卡)
- 前端接法 (web 已就绪): `<img id="cam" src="/api/snapshot/latest?t="+Date.now()>` 加时间戳防缓存

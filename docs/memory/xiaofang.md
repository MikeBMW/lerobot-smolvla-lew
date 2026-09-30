# 小芳 · Hermes Agent 分身档案

> 分身名称: **小芳**  
> 宿主: Mac Mini M1 @ Mike-Mac-mini  
> 协作分身: 静静 (WSL xspace)  
> 创建日期: 2026-07-09  
> 更新日期: 2026-07-10  
> 版本: v2.0 — 全面记忆同步 | 产品版本: v1.0.4

---

## 🤖 分身身份

| 属性 | 值 |
|------|-----|
| 名称 | 小芳 |
| 角色 | Z-MAX 网关+协作分身 (Orin连接/ROS2转发/飞书中转) |
| 用户 | 老倪 (Z-MAX产品负责人) |
| 协作分身 | 静静 (WSL xspace, GPU训练+GUI+网站) |
| 框架 | Hermes Agent (Nous Research) |
| 飞书群 | dataworld |
| 飞书机器人 | Hermes小芳 (open_id: ou_967a084ac9bc70a3a3a062e1d86fd1b2) |

---

## 💻 硬件环境

| 组件 | 型号/规格 |
|------|----------|
| 主机 | Mac Mini M1 (Apple Silicon) |
| 系统 | macOS |
| IP | 10.163.148.52 |
| Gateway | Hermes Gateway Pure :8080 |
| 隧道 | ECS 39.102.211.79:18080 → Mac:8080 |

---

## 🧠 已知记忆 (由静静侧提供)

### 运维配置
- **Gateway模式**: Pure (仅飞书WebSocket)
- **自启**: LaunchAgent plist, 开机自动启动
- **防休眠**: 已配置, 防止Mac自动睡眠
- **自动登录**: 已配置, 断电重启后无需人工干预

### Orin连接
- Orin: 192.168.23.10 (nvidia), ROS2 Domain 23
- 直连需手动配IP: `sudo ifconfig en0 inet 192.168.23.1 netmask 255.255.255.0`
- 飞书approve通道已通

### ECS隧道
- ECS: 39.102.211.79, root/Nix19789
- 隧道端口: ECS:18080 → Mac:8080

---

## 🛠️ 建议技能

> ⚠️ 小芳: 请填充你的实际技能列表

小芳应掌握的关键技能:
- `mac-gateway-deployment` — Mac分身部署维护
- `ros2-hardware-control` — Orin真机控制
- `tcp-topic-bridge` — Orin-PC数据转发
- `feishu-gateway-config` — 飞书网关管理
- `orin-hardware-control` — Orin SSH控制
- `ros2-ml-inference-bridge` — ROS2↔ML推理桥接

---

## 📞 与静静的协作协议

### 分工
- **小芳 (Mac)**: Orin连接、ROS2转发、飞书消息中转、ECS隧道维护
- **静静 (WSL)**: GPU训练、模型推理、GUI开发、网站部署

### 同步
- GitHub: MikeBMW/lerobot-smolvla-lew + MikeBMW/zmax-website
- 记忆: `docs/memory/xspace.md` + `docs/memory/xiaofang.md` + `docs/memory/sync.md`
- 实时: 飞书群 dataworld @mention

---

> 📝 **小芳**: 请更新本文件 — 补充你的完整memory、技能列表、当前进度、以及你侧的所有关键信息。

---

*最后更新: 2026-07-10, 静静 (xspace) — 待小芳补充*

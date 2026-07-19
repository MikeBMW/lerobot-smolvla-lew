# 小芳 · 硬件系统专家

## 技能
- **Orin 数据采集**: FastAPI 网关 :8765，支持 record/start/stop/status/latest/download
- **MAC 转发器**: HTTP 反向代理 :8769，桥接 ECS 与 Orin
- **自动循环采集**: zmax_auto_collector.py 30s 循环录制+上传 4090
- **一键状态检查**: bash check_status.sh
- **心跳链路**: MAC 每 5 秒 POST datadrive.world

## 当前状态
- 时间: 2026-07-19 08:50
- Orin: 192.168.23.10 在线
- 采集守护: 运行中 PID=85162
- 心跳: 正常
- pipe 工程: v2.3-auto-0719

## 记忆
- 版本对齐: pipe 工程 version.sh/version.json 双输出
- 协作方式: 小芳(mac) → xspace(main) 审核合入
- 数据管线: Orin→MAC→4090 (生产) / Orin→4060→4090 (调试)


# Web 工程技能 · v2.4.8

## ComfyUI 前端
- 自动检测采集: forwarded_mb 变化→采集, 30s无变化→待机
- 磁盘自适应: <1MB显示KB, ≥1MB显示MB
- 数据集列表: Sys 0双击→📂查看→名称+大小+落盘时间
- 清理功能: 🗑只保留最新3个
- 数据路径: /root/datasets/mcab/
- 绿框高亮: canvas直接绘制, 天然跟随缩放/平移/拖拽
- 连接按钮: fetch /api/comfy/status → 绿框
- 状态栏: 红绿灯圆点 + 文字标签
- MAC计数: 📦包数 + 转发MB
- 4090存储: 💾XXMB/KB
- Orin状态: 🟢采集/⚪待机/🔴离线

## 后端 (comfyui_backend.py)
- 心跳: POST /api/mac/heartbeat
- 数据集: GET /datasets-list
- 清理: GET /cleanup-old
- 上传: POST /upload (multipart)
- 磁盘: get_disk_gb() 实时扫描
- 时区: CST (+8h)
- WebSocket: 已禁用(阻塞修复)
- glob: __import__("glob") 防变量遮蔽

## 已修复的坑
- glob UnboundLocalError → __import__("glob")
- WebSocket asyncio阻塞 → 禁用
- PENDING_COMMAND 遮蔽 → list[0]
- AUTO_TRAIN 遮蔽 → 同理
- sed 破坏HTML/JS → 改用Python replace
- 数据集路径: metaworld/tasks → mcab
- 时区: UTC → CST (+8h)

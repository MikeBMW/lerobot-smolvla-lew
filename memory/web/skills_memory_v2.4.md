# Web 工程 · 技能记忆 v2.4-sync-0719

## ComfyUI 前端 (v2.3.2 → v2.4)
- 世界坐标缩放: ctx.setTransform(dpr*zoom) + getPos(clientRect)
- CSS脉冲层: addPulseOverlay() + @keyframes动画
- 三阶段流水线: Orin(MACP)→MAC转发→4090训练
- 仪表盘工作流面板: #wf-panel右侧抽屉5s刷新
- 硬件连接: toggleConnect→fetch /api/comfy/status→绿框
- 工程品牌顶栏: Z-MAX logo + 渐变 + 悬停动效
- 侧栏重设计: 180px宽 + 分组大写 + 悬浮动效

## 4090 后端 (v2.3 → v2.4)
- HTTP心跳: POST /api/mac/heartbeat → {"st":"ok","cmd":...}
- 命令通道: PENDING_COMMAND[0] 消费模式
- 自动训练: POST /upload → cleanup_disk() → auto_train()
- 磁盘管理: 保留5npz + 删MCAP + W&B周清(每周日3am)
- Nginx: client_max_body_size 500m

## 关键修复
- Python变量遮蔽: 全局变量改用list[0] wrapper
- do_POST空响应: 全局send_response(200) at top
- 节点选择: getPos逆变换 clientRect/dpr/zoom - px
- sed损坏HTML: 统一用Python read+replace+write
- json-save重复: 清理do_GET副本, 仅do_POST

## 运维要点
- ECS: 39.102.211.79 宝塔nginx SSH隧道50053→50054
- Python: /root/.local/share/uv/python/cpython-3.12.13-linux-x86_64-gnu/bin/python3.12
- 部署: scp → /www/wwwroot/datadrive.world/
- 缓存控制: nginx no-cache for comfyui.html + manifest.json

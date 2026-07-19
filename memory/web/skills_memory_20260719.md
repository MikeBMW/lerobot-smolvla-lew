# Web 工程 · 技能与记忆 v2.3.2

## ComfyUI 前端
- 世界坐标缩放: canvas transform + getPos(clientRect/dpr/zoom - px)
- CSS脉冲层: addPulseOverlay() + @keyframes + requestAnimationFrame
- 三阶段: stage=1 Orin绿闪→stage=2 MAC绿闪→stage=3 4090红闪+训练
- 仪表盘: #wf-panel 右侧抽屉, 5s自动刷新
- 硬件连接: toggleConnect→fetch /api/comfy/status→绿框addOverlay()

## 4090 后端
- 心跳: POST /api/mac/heartbeat → {"st":"ok","cmd":...}
- 命令: POST /api/comfy/command → PENDING_COMMAND[0]
- 自动训练: POST /upload → auto_train() → train_h_jepa.py
- 磁盘: cleanup_disk() 保留5npz+删MCAP+W&B周清

## 已修复的坑
- Python局部变量遮蔽(PENDING_COMMAND/AUTO_TRAIN)→改list[0]
- do_POST响应空→全局send_response(200)
- 节点选择zoom后偏移→getPos用clientRect/x逆变换
- sed引号转义导致HTML/JS损坏→改用Python replace
- sidebar重复分组→git checkout clean重建

## 运维
- ECS:39.102.211.79 宝塔nginx SSH隧道50053→50054
- 4090: /root/.local/share/uv/python/cpython-3.12.13-linux-x86_64-gnu/bin/python3.12
- 部署: scp root@39.102.211.79:/www/wwwroot/datadrive.world/
- 缓存: nginx no-cache for comfyui.html

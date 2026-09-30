# 2026-08-08 容器管理框架 + 线程安全 + 远程训练执行

## 模型引擎 = 标准容器框架 (老倪定位)
模型引擎本质是 Docker 框架: 一处构建 → 远程训练(V100 amd64) / 本地推理(4060) / 端侧部署(Mac·Orin arm64)。
- 标准框架文件在仓库 `docker/`: Dockerfile(多阶段 base→train/infer, ARG TARGETPLATFORM 分 amd64-CUDA/arm64-CPU)、requirements.lock(锁定)、entrypoints/train.sh·infer.sh(zmax-train/zmax-infer 入口)、deploy/push.sh(remote/mac/orin 三端)
- GUI: 模型引擎页 🐳 容器管理框架区 = 状态标签(_ct_status, 轮询更新) + 按钮组(🔼构建·上传远程 / 🚀容器训练 / 🎮容器推理 / 🍎推送Mac / 🤖推送Orin) + _container_action(kind) 后台线程分派
- 上传按钮逻辑: 本地有 docker 且镜像 → save+scp+load; 本地无 docker(常见, WSL无) → 自动 fallback 远程 git pull + docker build (明确日志提示)

## 线程安全 (GUI 跨线程崩溃 — 老倪报"容器管理又崩溃")
- 根因: 后台线程直接操作 Qt 控件 (_log 的 log_text.append/scrollbar, 按钮 setEnabled) — 非线程安全偶发崩
- 修复模式: `_log` 检测 `threading.current_thread() is main_thread()` — 非主线程 → `QTimer.singleShot(0, lambda t=text: self._append_log(t))` 回主线程; 按钮恢复同样 singleShot
- 所有后台线程 (_upload_container/_container_action/_connect_gpu worker) 遵循此模式

## xdotool 操作真实窗口 (老倪: "操作窗口按钮, 不能只在后台")
- WSLg 下 apt 装 xdotool; 找窗口: `xdotool search "" | while read w; do xdotool getwindowname $w; done`
- 盲点迭代: 估算坐标点击 → 查窗口标题变没变 → 调整; 无控件树可读, 只能试
- 教训: 多点几次 GUI 重启后窗口可能不显示 — kill -9 后守护(gateway PID 405)自动拉起, 15s 后确认新 PID + 窗口名

## 远程训练执行模式 (V100 服务器计时 — 快)
- 训练参数是 `--config_path`(下划线!); `--config-path`(短横线) → `unrecognized arguments` — 本地 GUI training_backend 也是下划线
- 输出实时性两个坑: ①python 非 tty 块缓冲(4K 攒批) → 命令加 `-u`; ②tqdm 用 `\r` 刷新不换行, `for line in p.stdout` 永远等不到 → `_run_cmd` 改 bytes 块读(p.stdout.read(4096)) 按 `\r`/`\n` 分行, 每行 emit 日志(截 600 不简化)
- 队列推进防误判: on_train 有数据准备延迟, 15s 轮询 pgrep 会误判"完成"秒推进 → 记录 _zoo_start_ts, 启动后 45s 内不判完成; 进程在则重置窗口
- ssh 后台长任务: `setsid bash x.sh > /dev/null 2>&1 < /dev/null & disown` (nohup/普通& 在 ssh 断开后被杀); 验证 `pgrep -f 'zoo_train_v3'`
- 远程 venv 是 --no-deps 装的 lerobot — 反复缺包: accelerate/tensorboard/transformers/datasets/av — 报错就补; 每个 config 数据 root 要 sed 统一 (远程只有 data/metaworld_peg(_grab6))

## transformers 版本大战 (踩坑史 — 结论: 锁定 4.44.2)
| 版本 | 崩点 |
|---|---|
| 5.14.1 | tensor_parallel.py `torch is not defined`; AutoProcessor 导入失败 |
| 5.5.4 | integrations/accelerate.py、tensor_parallel.py 等缺 torch import; `from transformers.generation import GenerationMixin` 路径改; sed 修还撞 from __future__ |
| 4.49/4.51 | `Qwen2_5_VLTextConfig` 不存在 (eo1 policy) — 可 try/except 降级 |
| **4.44.2** | 飞书端 v6 镜像验证稳定 — 最终基线 |

- 修复代码(不是版本): GenerationMixin import 改 `transformers.generation.utils`(4.x/5.x 都兼容, 3 文件); eo1 TextConfig try/except 降级
- 教训: 环境依赖锁定比反复升级重要; 本地 .venv 与远程 venv/容器版本要一致(本地能跑 ≠ 远程能跑, 5.5.4 本地 OK 远程崩)

## 容器运维 (与飞书端协同)
- 容器可能被飞书端暂停/删除/重建 — 操作前 `docker ps -a` 对账; 容器重建后 /tmp 脚本丢失要重拷 (docker cp)
- 容器内 nvidia-smi 不存在 — 用宿主机查 GPU
- 容器 v4-final 镜像缺 accelerate — 补 `pip install accelerate`(静默 -q 会假失败, 去掉 -q 看输出)
- 多端协调: 飞书端容器路线(torch2.4.1+cu124) vs 我 venv 路线 — 老倪要求"干一个事情": 接管后停掉重复路线, 监控脚本(容器优先) cron 每 20min 飞书汇报

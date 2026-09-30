# 全息 ID 系统 + 本地容器训练 (2026-08-08)

## 全息 ID 管控 (老倪深度交互需求)
需求演进: 表格列ID(被否"我不会去用表格查询") → 按钮文字带ID(被否) → **每个控件左下角青色小字 ID**(最终)。
- ID = 3D 坐标 `X.Y.Z`: X=页(P01~P12), Y=区块(01训练/02容器/03配置/04数据/05评估/06日志/07导航/08状态/09对比/10部署), Z=控件序号
- 页表: P01首页 P02数据集 P03模型引擎 P04评估 P05硬件 P06配置 P07监控 P08场景 P09版本 P10推理 P11画布 P12数据空间
- 注册表(全局数据空间): `self._holo_coords[cid] = (widget, name, type, getter)`; 简写 B-xx/S-xx 兼容保留
- 执行: `_holo_act("P03.01.01")` → 按钮click/开关toggle/下拉showPopup; 返回"✅ 已执行 {id} ({name})"
- 可读描述: `_holo_coord_desc` → "模型引擎·训练区·控件01"

## 角标实现铁律: 叠加式 QLabel, 绝不 replaceWidget
- ✅ `_holo_badge_overlay(widget, id)`: `QLabel(id, widget)` 子控件 + `move(2, max(0,h-lbl.h-2))` + `raise_()` + `setattr(widget,"_holo_badge_lbl",lbl)` — 不动布局, 所有 Qt 控件可用, 不崩
- ❌ replaceWidget 递归包装(旧方案): 复杂布局下 **GUI 启动即 segfault**(offscreen 与真实 DISPLAY 都崩, exit 139) — 全控件打标必须叠加, 不能动布局
- 主窗口 `__init__` 尾部 `QTimer.singleShot(1500, lambda: self.model_engine._holo_apply_all(self))`; 太早(构造中)控件未建齐
- `_holo_page_of(w)`: parent 链找 objectName 含 home/dataset/model_engine/... → P01~P12, 匹配不到 P00
- apply_all 遍历 `findChildren(QWidget)` 目标类型: QPushButton/QCheckBox/QRadioButton/QComboBox/QLineEdit/QTableWidget/QGroupBox

## 画布节点 ID — 加错位置教训
- 画布节点类是 **SimNodeItem**(paint ~1777 行), **不是** CICDStageItem(~1018 是 CICD 弹窗) — 加错后老倪立刻发现"左下角没有青色小字"
- SimNodeItem.paint 末尾加: `painter.drawText(QRectF(6, h-12, w-10, 11), nid)`; nid = `node.get("nid") or f"P11.{node.get('id',0)%100:02d}"`; 色 #00d4aa 7px
- 视频节点名字在左下角(h-18) — ID 放 h-12 接近但不冲突

## 本地训练强制容器化 (老倪: "删掉本地训练代码; 强制使用docker训练")
- WSL2 无 /dev/nvidia* → **--gpus all**(NVIDIA Container Toolkit); 远程 Linux 才用 --device 透传
- 命令模板: `sudo docker run --rm --gpus all -v {root}:/app -w /app -e PYTHONPATH=/app/src --entrypoint python zmax-std:1.0 -u -m lerobot.scripts.lerobot_train --config_path /app/xxx.yaml`
- tmp_cfg 的 root 必须 sed 成容器内路径 `/app/data/...`(挂载 -v root:/app); 原始 config root 常指向无数据的 metaworld_act → 秒崩
- output_dir 时间戳防 FileExistsError(act_metaworld_final 已存在即崩)
- vla_touch/awe_zflow 独立脚本(train_vla_touch.py/train_awe_zflow.py)也走容器, --data-root 转 /app 路径
- 评估/rollout/报告全容器化(rollout_video.py/compare_models.py/generate_report.py)
- 飞书端 zmax-std:1.0 构建法: **直接 COPY 本地验证过的 site-packages**(绕开 pypi.nvidia.com 慢/超时), 与 .venv 完全一致
- requirements.lock 不写 torch 行 — torch 由 Dockerfile 预装(否则重复安装 BUILD 失败)

## 模式卡片 = GPU 引擎 (老倪纠正: 本地运行≠推理)
- 三卡片: 远程训练(train→gpu_mode=remote) / 本地运行(infer→**local=本地训练**) / 端侧部署(deploy→推送Mac/Orin)
- 老倪纠正过: 点本地运行+Start 弹 rollout scope 是错的 — **本地运行 = 本地训练**(容器), 不是推理
- ▶ Start 通用按钮(不写 Training): 模式决定动作; ⏹ Stop=清 _zoo_queue+停 timer+pkill lerobot_train+simulink.on_stop; Pause 已删
- 画布每模型训练开关(7 个 train_gate 节点带 policy 参数, 放最前端像 YOLO 开关) + 控制台 QCheckBox 双通道; on_train 开头 `_train_gate_state(policy)` 关则跳过

## 容器训练显示与反馈 (老倪: 要看到真实状态)
- 本地容器轮询: `sudo docker ps` + `docker logs --tail 3` → 解析 Training %/loss → 日志区"├ 进度: ..."
- 容器启动打印属性树(位置/镜像/GPU/挂载/PYTHONPATH)
- 远程不可达明确提示: 3s ConnectTimeout 快速探针, 失败直接"⚠️ 远程 GPU 连不上(已关机/网络不通)— 使用本地引擎"; **绝不显示虚假连接成功**(connected 标志检查)
- 日志智能滚动: `at_bottom = scrollbar.value() >= maximum()-12` 才跟随; 用户看上面绝不跳底("别总自作多情")

## 远程运维 (2026-08-08)
- SSH 曾换端口 24424→24340, 密码改 ahWat3se(存 ~/.zmax_ssh.json, GUI 自动读)
- 远程磁盘曾 100% 满(191/196G) → docker builder prune + rmi 旧镜像(full/v3-final/ready/v2) + rm /tmp/*.tar → 清到 80% 才能训
- 容器训练秒退排查: docker run 前台看输出(不 -d)是标准诊断法; --rm 容器退出即删, docker ps -a 看 Exited 码

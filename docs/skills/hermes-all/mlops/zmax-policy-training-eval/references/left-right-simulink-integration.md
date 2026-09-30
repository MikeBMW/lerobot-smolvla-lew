# left_right Simulink 集成 (2026-08-10)

## ▶ 运行 = 自动训练 (start_sim → on_train)
- 触发: start_sim 检测画布有节点名 == "◉ LeftRightPolicy" → `self.on_train(policy="left_right")` 并 return
- ⚠️ **必须放在 `_canvas_stage_nodes()` 检查之前**: left_right 画布含「📄 PDF 插拔方案报告」节点,
  名字命中 NODE_RUN_ACTIONS 的 `("PDF", on_pdf_report)` → 放后面永远走 PDF 分支, 训练不触发
- on_train 需加 left_right 分支 (否则落 ACT else 分支用错配置): 
  `cfg_path = root/configs/policies/config_left_right.yaml`, `ts_dir = "left_right_" + ts`, `pname = "LeftRight"`
- 训练开关: `_train_gate_state` 画布无 train_gate 节点 → 放行 True (不弹跳过)

## config 位置 (老倪 2026-08-10: "yaml 为什么要放工程目录下")
- 新训练配置放 `configs/policies/config_left_right.yaml` — 根目录 64 个 config_*.yaml 是历史遗留勿动
- on_train 读模板 → 生成 `config_left_right_runtime.yaml` (output_dir 加时间戳 + root 重写
  `/app/data/<rel>` 容器路径) → 容器内 `/app/config_left_right_runtime.yaml`, 用完 os.remove

## 容器训练实测 (zmax-std:1.0, 无需重建镜像)
- 镜像挂载最新源码 (`-v root:/app -e PYTHONPATH=/app/src`) → left_right 直接注册可用:
  `_get_policy_cls_from_policy_name('left_right')` → LeftRightPolicy, 547K+87K 参数
- 3000 步 / bs8 / lr 1e-4 / 39D 全量 12 集 3600 帧: 4060 实测 ~36 step/s, 1分22秒, loss→0.02
- **dataset.episodes 占位 `[0]` 必须删** (只训 1 集无效); 删行用全部 12 集
- 产物: `outputs/train/left_right_<ts>/checkpoints/003000/pretrained_model/`
  (model.pt + config.json + left_right_pre/postprocessor) 
- Scope 曲线前置: `reports/train_curve_left_right.json` 必须存在 (ckpt 键指向 checkpoints 目录),
  手动跑训练后需补建, 否则 load_policy 报 FileNotFoundError

## node_logic 外部源码映射 (右键节点看真实实现)
- 详见 zmax-console references/gui-discipline.md「节点源码定位」节 — 模式通用:
  `_EXTERNAL_LOC` 映射 + `get_node_location` 外部优先 + `get_external_source` 按符号截取

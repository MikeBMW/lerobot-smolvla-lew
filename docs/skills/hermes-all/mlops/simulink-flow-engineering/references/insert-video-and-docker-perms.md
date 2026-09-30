# 插拔视频生成链路 + docker 训练产物权限 (2026-08-12)

## docker 训练产物权限 → GUI 启动崩溃 (最隐蔽的坑)

- **症状**: 训练后重启控制台, GUI 启动即崩。崩溃日志尾:
  `PermissionError: [Errno 13] Permission denied: .../training_state/optimizer_param_groups.json`
  (DatasetModule._refresh_train_results 遍历 outputs/train/ 做 getsize 求和)
- **根因**: docker 容器内训练产物是 **root 600** 权限(`-rw------- root root`),
  当前用户 xspace 读不了; ls 显示 `-?????????` = 父目录/文件不可读元数据
- **修复**: `sudo -n find outputs/train/ -type d -exec chmod 755 {} +` +
  `sudo -n find outputs/train/ -type f -exec chmod 644 {} +`(1313 个文件量级)
- **防御**: 遍历代码 try/except 包裹(`sz=0.0; try: sz=sum(...getsize...) except: sz=0.0`),
  任何文件不可读不再崩 GUI
- **铁律关联**: 记忆里"模型 chmod644"就是这条 — docker 训练完必须放开权限,
  否则部署/视频生成/控制台遍历全部读不了

## gen_insert_video.py 模型加载 4 连坑 (视频生成"慢又不生成")

视频生成脚本(tools/gen_insert_video.py)从**写死旧模型**改为加载**最新双脑 checkpoint**:

1. **模型源选择**: 原写死 `outputs/rl_peg/full_pipeline.pt`(旧 RL 管线, 8/10)
   → 改 `_load_brain()` 遍历 `outputs/train/left_right_*/checkpoints/last/pretrained_model/model.pt`
   - ⚠️ 排序必须**按 mtime**(字母序 reverse 会把 `left_right_std` 排最前 → 加载错模型)
2. **归一化参数**: 新 checkpoint 的 model.pt 只有 `{left, right, obs_dim, act_dim}`,
   **没有**旧模型的 xm/xs/ym/ys → 从 Lerobot preprocessor/postprocessor safetensors 读(标量整段):
   - `left_right_preprocessor_step_3_normalizer_processor.safetensors`: `observation.state.mean/std` → xm/xs
   - `left_right_postprocessor_step_0_unnormalizer_processor.safetensors`: `action.mean/std` → ym/ys
3. **RightBrainWM 结构两版不兼容**:
   - 训练产物 model.pt 的 right 键 = `{enc.*, pred_next.*, contact_head.*}`(modeling_left_right.py 版,**无 align_head**)
   - train_full_pipeline.py 版多 `align_head` → load_state_dict 报 Missing key(s) align_head
   - 修: import 改用 `from lerobot.policies.left_right.modeling_left_right import RightBrainWM`
     (sys.path 加 `src/`), LeftBrainMLP 两版结构一致可留旧 import
4. **右脑返回 2 值**: modeling_left_right 版 `forward(obs, act) → (next_obs, contact)`;
   旧管线版返回 3 值(next_obs, contact, align_delta) → 脚本解包 `_, pred_cont, _ = right(...)`
   报 `not enough values to unpack (expected 3, got 2)` → 改 2 值解包(两处)

验证模式: `.venv/bin/python` 直接调 `_load_brain()` 打印归一化四元组 + 前向形状
(obs→act 4D, right→(39D, 1D contact∈(0,1))); 前向测试的输入 tensor 必须 `.to(DEVICE)`(模型在 cuda)

## 训练完自动生成视频 (force 模式)

- 训练完成(_start_worker `_done(ok, summary)` stage=="train" 且 summary 含 left_right)
  → `QTimer.singleShot(800, lambda: self.on_insert_video(force=True))`
- on_insert_video(force=False, **kw): `force=True` 跳过"已存在直接打开"检查直接重新生成
- **force 生成完成不自动弹播放器**(`if not force: _open_video_for_user(mp4)` else 只 log) —
  用户训练监控中弹窗打扰(记忆"WSLg 弹窗零容忍"同源)
- 效果: 训练完后台 48s(GPU)生成, 用户点节点秒开, 不等生成

## 视频打开链路(最终版)

`_open_video_for_user(mp4)`: 复制到 `/mnt/c/Users/Public/ZMAX_videos/` +
`subprocess.Popen(["cmd.exe", "/c", "start", "", _win], cwd="/mnt/c/Windows")`
- explorer.exe 打开**文件**从 WSL 启动静默失败(UNC cwd) → 文件一律 cmd start;
  explorer.exe 只用于打开**目录**(open_node_source 源码目录)
- 实测链路: `cd /mnt/c/Windows && cmd.exe /c start "" "C:\...mp4"` rc=0 且播放器弹出

## 视频生成慢/内容不对的诊断 (2026-08-12 补)

- **"生成视频好慢" = _pick_seed 在遍历 seed**: `_pick_seed(seed_max=11)` 无渲染试跑最多 12 个 seed × 300 步,
  新模型成功率低时遍历久(200s+ 无输出属正常, 不是卡死); GPU 利用率低(5%)也正常(试跑无渲染)
- **"视频是 model zoo 的" = 打开的旧 mp4, 不是生成错**: reports/insert_success_demo.mp4 时间戳 17:21(旧模型 16:49),
  用户 19:59 训练完点 ▶ 视频 → \"已存在直接打开\"弹旧视频 → 误以为生成错 → 检查 mp4 mtime 与训练时间是否匹配
- **训练完自动生成(force)没触发** = 训练时 GUI 实例跑的是旧代码(自动生成是后加的) — 手动 `.venv/bin/python tools/gen_insert_video.py` 补生成即可
- **新模型插拔失败(seed 0/1 卡在抓取)**: 快速诊断用状态机全流程试跑(不是只跑 ST_APPROACH —
  单阶段测试永远卡住误判模型坏): 主循环按 right 的 contact 推进状态机(ST_APPROACH→GRASP→LIFT→TRANSFER→INSERT→DONE),
  300 步内 done 算成功; 4 seeds 成功率对比新旧模型定位"训练退化"vs"环境问题"

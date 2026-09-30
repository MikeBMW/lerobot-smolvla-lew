# 数据闭环控制台模型选择器 (2026-08-07 老倪需求: 看所有训练模型→选一个→sim-to-real→stage3)

位置: `tools/gui/simulink_module.py` → `PipelinePanel` (数据闭环 CICD 控制台, 双击画布「🎯 数据闭环控制台」按钮打开)

## 需求原文
"数据闭环控制台，将5模型对比训练好的模型，用户可以选择一个模型，比如AWE，用户要能看到所有训练好的模型，模型属性，例如名字，训练时间，要可以看到，然后将这个模型，sim to real，然后stage 3"

## 实现 (UI 插入点在状态栏 `lay.addWidget(bar)` 之后、6环节流水线之前)
```
🤖 模型 [ACT · 08-07 16:18 ▾]  属性: ckpt=outputs/train/act_pegdata_4000/checkpoints · 训练 08-07 16:18 · 4000 步 · 尾loss 0.585
        [🎯 Sim-to-Real (S2)]   [🚀 Stage 3 真机微调]
```

## 4 个方法
- `_reload_models()`: glob `reports/train_curve_*.json` → 显示名映射 (act→ACT/smolvla→SmolVLA/smolvla_lew→SmolVLA+LEW/vla_touch→VLA-Touch/awe_zflow→AWE/expert_mlp→MLP 蒸馏/expert_policy→官方专家) → cmb 项 = `"{name} · {ts}"` (ts 从曲线 json 的 `ts` 字段 `%Y%m%d_%H%M%S` → `MM-DD HH:MM`, 缺失用文件 mtime); `_model_meta[name] = {policy, ckpt, loss, ts, steps}`; 默认 `setCurrentIndex(2)` = AWE
- `_show_model_attr()`: 属性 QLabel 显示 ckpt/训练时间/步数/尾loss
- `_on_sim2real()`: 写 `docs/PIPELINE_STATE.json` stages["2"] = {model, policy, status:"running", ts} + 日志 "🎯 Sim-to-Real (S2): {name} → Orin 真实数据零样本测试"
- `_on_stage3()`: 写 stages["3"] = {model, policy, status, ts} + 日志 "🚀 Stage 3 真机微调: {name} · lr 1e-5 · backbone 1e-6"

## 验证 (offscreen)
⚠️ 不能直接 `PipelinePanel(module)` 构造再测 (__init__ 有 2s QTimer + _remote_timer 10s 轮询, offscreen 事件循环会挂/资源泄漏)。
正确: `pp = sm.PipelinePanel.__new__(sm.PipelinePanel)` (不调 __init__) + 手动挂 `pp.module/cmb_model/lbl_model_attr/_model_meta` → `_reload_models()` → 断言 cmb 项数 (8) + AWE 项存在 + 属性文本; `_on_sim2real/_on_stage3` 测试前 **monkeypatch `pp._refresh = lambda: None`** (否则 _refresh 访问未构造的 lbl_stage_now 等崩 `super-class __init__() never called`); `_STATE` 指到 /tmp 测试文件, 断言 stages["2"].model == "AWE" 后清理。

## 相关
- 三阶段 STAGE_DEFS: S1 MetaWorld 仿真训练 (backbone 冻结 lr1e-4) / S2 Sim-to-Real 零样本测试 (量化 Reality Gap) / S3 Orin 真机微调 (lr 1e-5, backbone 1e-6, ensemble 0.01)
- 状态文件 `docs/PIPELINE_STATE.json` 每 2s `_refresh` + 每 10s `_poll_remote` (Orin 心跳/推理/数据量)

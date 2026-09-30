---
name: zmax-full-system-loop
description: Use when 同步真机模型参数/标定接口/联合训练/LoRA/闭环。
version: 1.0.0
author: 静静 (Hermes)
license: internal
metadata:
  hermes:
    tags: [zmax, sim2real, lora, joint-training, calibration, robot-model, data-loop]
    related_skills: [zmax-real-closed-loop, rokae-direct-control, orin-lan-direct-access, zmax-policy-training-eval]
---

# Z-MAX 全系统 采-训-推 闭环 + 真机模型/标定真源 + LoRA (2026-09-22 实跑)

## When to Use
- 「同步真机数据/URDF/质量/惯性/自由度，全面更新状态空间仿真数据」
- 「全系统联合训练(大模型层/L4 INTACT/L3 Smolvla/L2 YOLO+2D→3D)」「适配或增加 LoRA」
- 「标定参数接口」「sim to real 全系统数据闭环」；或要给某层做 LoRA 微调/合并部署
- 前置: 真机只读 tap 在线 (否则采集体检环会 fail, 不编造)

## 红线 (脚本里写死, 不是口号)
只读: 不调 `/move*` `/hmi/command` `/execute_external_task` `/gripper_driver` `/state_machine/*`
不干扰生产: 训练前查 GPU 空闲; 不 kill 非本编排器进程; 不动 Orin
不编造: 缺标定/缺数据/缺权重 → `null` + 原因 + 非零退出, 禁用默认值顶替

## 一、机器人模型单一真源
```bash
R=/home/ubuntu/lerobot-smolvla-lew; cd $R; P=gui-venv311/bin/python
$P tools/robot_spec_sync.py          # URDF+真机只读实测 → config/robot/zmax_robot_spec.json
```
产出: DOF / 关节轴 / 逐轴限位(位置·速度·力矩) / 连杆质量·质心·惯量张量 / 工具链 /
**产线 TCP 反解**(法兰→`/robot/tcp_pose`, 多帧只读反解) / 控制器负载(setToolset 回读) / FK 校验。
2026-09-22 实测: DOF6 · 6 连杆 13.622 kg · 负载 1.51 kg · TCP `[-0.015875,0.015293,0.260422]` ·
FK 对真机 tcp **3.52 mm**。

**FK 口径铁律**: `t += R_parent·origin_xyz` 先做, 再 `R = R_parent·R(rpy)·Rot(axis,q)`。
顺序写反只影响**带 rpy 的末段工具关节**(6 个运动关节 rpy 全 0 看不出来) → 表现为 ~136 mm 假偏差。

## 二、统一标定接口
```bash
$P tools/zmax_params.py --sync      # 合并各源 → config/calib/zmax_calib.json
$P tools/zmax_params.py --check     # 就绪度; 有关键缺口 → 返回码 1
$P tools/zmax_params.py --fk <q1..q6> --live   # 真源几何 FK 对照真机 tcp 真值
```
未标定项 (2026-09-22): `T_base_cam`(需零运动人工拖动 10+ 位姿, `tools/board_handeye_solve.py`) ·
`plane_z`(现场量) · 示教几何(`tools/ss_geom_calib.py --record peg_head|goal|aoi`)。
消费方一律 import 读真源: `tools/gui/yolo_perception.py`(台面高度) · `tools/real_truth.py`(示教几何/夹具偏移)。
仿↔真桥: `$P tools/sim2real_bridge.py` → `config/robot/zmax_sim2real.json`。

## 三、LoRA (自实现, 免依赖)
```bash
$P tools/lora_inject.py --selftest   # 5 条物理断言 (两套 venv 都该全绿)
```
· 输出 `base + (α/r)·B·A`; **B 零初始化 ⇒ 注入瞬间逐位等价**(max|Δ|=0)。
· 注入后基座全冻结, 只有 `lora_A/B` 可训 → 训练 ckpt 里基座张量与起点**逐位相同**
  (仅 BatchNorm `running_*` 会变, 属 buffer 正常)。
· L4 接入: `INTACT-JEPA/train.py` 的 `ZMAX_LORA=1` 守卫 (默认关)。2026-09-22 实测:
  注入 112 层 / 可训 4.41% / 200 步 134s。
· **部署/评测必须合并**: `lora_merge_ckpt.py --ckpt <lora.pt> --ref <起点.pt> --out <merged.pt>`
  (键集合与起点不一致 → 拒绝落盘); 不合并直接判闸 = 拿到的是基座结果, 会误判"没效果"。
· L3 (lerobot) 两条引擎 (`--l3-lora-engine`):
  · `peft` = lerobot 原生 PEFT (`cfg.peft` 段写进 YAML; 不要用 `--peft.xxx` 命令行, draccus 对可空
    子配置不可靠)。**8GB 卡不可用**: peft 0.21 把适配器输入强制转 fp32 (`_cast_input_dtype`),
    四档 (all-linear / q,k,v,o × batch 8/4/2) 全 OOM, 栈停在 smolvlm 视觉塔 MLP fc2;
    `LoraConfig.autocast_adapter_dtype` 在 0.21 已移除 ⇒ 配置关不掉。
  · `local` (**默认**) = 自研 `tools/lora_inject.py` 经 `lerobot_train.py` 的 `ZMAX_LORA_LOCAL=1`
    守卫接入 (默认关=零回退): 低秩两次小 matmul + A/B 降到输入 dtype ⇒ 无 fp32 大激活。
    实测 256 层 / 可训 0.4436% / batch4 / 2.29s per step / 峰值 6.25GB / 0 OOM。
  两条都要 `exclude_modules=['vision_model']` 排除视觉塔 (lerobot `PeftConfig` 已加该字段)。

## 四、联合训练编排
```bash
$P tools/joint_train_all.py --env-check          # 各层前置体检
$P tools/joint_train_all.py --dry-run            # 计划 (不执行)
$P tools/joint_train_all.py --steps 200          # L4(LoRA)+L3(原生PEFT)+L2+LLM 体检
$P tools/joint_train_all.py --only L4 --no-lora-l3
```
L4=INTACT(train.py, data=zmax_v6, 续自 `intact_goal_optical_insert_v6d9_s3072/weights_epoch_1.pt`) ·
L3=`lerobot_train`(policy=smolvla_lew, 起点 `outputs/train/smolvla_lew_sim/checkpoints/000300`) ·
L2=`tools/yolo_annot_train.py`(真机标注帧) · 大模型层=`tools/llm_layer_check.py`(只读)。
取证 `reports/joint_train_<ts>/{L4,L3,L2,LLM}.log + stages.jsonl + summary.json`。

## 五、六环闭环
```bash
$P tools/sim2real_loop.py                        # ①采集只读体检 ②归档 ③数据口径 ⑥部署指针
$P tools/sim2real_loop.py --train --eval         # 加 ④训练 ⑤评测
```
归档用硬链接 (零额外盘); **硬链接被 `protected_hardlinks` 拒时自动回退复制**并逐条记 `method`
(容器 root 写的 tap 文件归 ubuntu 时必被拒; 不回退 = MANIFEST 有记录但文件没落地)。

## 坑 (全是实测)
1. **LoRA 补丁写成 post 步骤 = 整轮没开 LoRA** (日志 `'peft': None, use_peft=False`) → 必须
   mkcfg 之后、训练启动之前。
2. **8GB 卡 L3 LoRA 必 OOM**: peft 对适配器输入做 **fp32 转换** (`tuners_utils._cast_input_dtype`),
   VLM 大激活多留一份 ⇒ `all-linear`→`q,k,v,o` + batch 8→4→2 三档都顶爆。要么 12GB+ 卡,
   要么只挂动作专家头; L3 全参 batch8 反而能跑。
3. `lora_inject` 顶层子模块名不含 `.` (如 `nn.Sequential` 的 `"0"`) → `rsplit` 取 attr=None 被跳过
   ⇒ **注入 0 层而"逐位等价"断言仍然通过**(注入 0 层当然等价!)。自检必须同时断言"确实注入了 N 层"。
4. **同口径 A/B 才算证据**: 同 h5 · 同 clips · 同 repeats · 同 seed · 同 `--skill on`, 只换权重。
5. 判闸只看 MAE 会漏 KPI-1: **必须看逐轴 |corr|** (dy 长期是卡点轴)。
6. 相机快照"有 snapshots 目录"≠权重下全 → 按 `*.safetensors` 实际体积判。

## 验收命令 (一轮跑完)
```bash
$P tools/robot_spec_sync.py && $P tools/zmax_params.py --check
$P tools/lora_inject.py --selftest
$P tools/joint_train_all.py --steps 200
$P tools/lora_merge_ckpt.py --ckpt <lora>/weights_epoch_1.pt --ref <起点>.pt --out <lora>/weights_merged.pt
CUDA_VISIBLE_DEVICES= INTACT_POLICY=<merged.pt> $P tools/intact_replay_check_v4.py \
  --skill on --clips 60 --repeats 1 --device cpu --out reports/lora_eval.json   # 与起点同口径对照
$P tools/sim2real_loop.py --train --eval
```

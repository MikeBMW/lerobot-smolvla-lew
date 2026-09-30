# 状态差分哨兵 / 两类"假失败" / A/B 判据隔离 (2026-09-23 全量 pipeline 实跑)

配套 `references/multi-stage-orchestrator-rc-and-gpu-oom-2026-09-22.md`(逐阶段读 rc、OOM 真凶是资源冲突)。
本文补三件那篇没有的: **哨兵判据用状态文件差分**、**闸门不许把可选件计成失败**、**A/B 两臂相同先怀疑判据**。

## 1) 状态文件差分哨兵 (比扫产物更稳, 迟到/重试自动纳入)

让**链自己写一份纯文本状态**, 哨兵只比"内容变了没":

```
reports/fullpipe_<ts>/status.txt
START 2026-09-23 21:40:43 out=reports/fullpipe_20260923_214043
[L5_gen] start ...              / [L5_gen] RC=0 end 2026-09-23 22:24:06
[JOINT]  start ...              / [JOINT]  RC=1 end 2026-09-23 22:30:22
[EVAL]   start ...              / [EVAL]   RC=0 end 2026-09-23 22:30:55
DONE ...
[L3_retry] start 22:36:55 batch=2 tag=r4 / [L3_retry] RC=0 end 23:38:05   ← 重试往同一份追加
```

- 接力脚本形态: `run(){ name=$1; shift; echo "[$name] start $(date '+%F %T')" >> "$STATUS"; "$@" > "$OUT/$name.log" 2>&1; rc=$?; echo "[$name] RC=$rc end ..." >> "$STATUS"; }`
- 哨兵(`no_agent` cron): 读**最新** `reports/*/status.txt`; 与 `~/.hermes/scripts/.<name>_state` 比 → 相同则零输出(静默);
  变了 → 简报(每段日志尾部 3~4 行 + 关键指标); 含 `DONE` 或任何 `RC!=0` → 终态简报。**失败分支必须有**。
- 迟到/重试阶段只要**把 RC 追加进同一份 status.txt** 就会被自动纳入报告(重试换 `--tag` 避让输出目录)。
- 交付: CLI 会话创建的 cron 是 local-only; 要进群/进手机就让脚本**自己直推**(见 feishu 直推脚本模式), 或 `deliver=<平台:chat>`。

## 2) 两类"假失败" (都会让整链被判红)

**(a) 可选件被计成缺口**。LLM 阶段仅因 `qwen2.5-vl-3b` 权重未下全(`0MB < 门槛 3000MB`)就 rc=1,
而项目既定口径根本不用它(DeepSeek Vision API + `smolvlm2-500m` 兜底; 8GB 卡勿试 3B VL)。
修法: 闸门只统计**本次真会用**的件, 其余标 `xxx_informational: true` + 打印提示, **不计入 gaps**。
⇒ 闸门设计原则: "我们决定不用的东西"不得成为失败条件。

**(b) CUDA OOM 的占卡者是"另一个训练 job"** —— 与"先腾显存"互补: 当占卡的是不能杀的别人/长训练时,
正确杠杆是**降 batch**, 不是改模型:
`--l3-batch 2` + `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` + `--gpu-wait 1800`(等余量)。
实测: 报错时只剩 6.62 MiB(另一训练 1.5GB + 三个常驻采集 ~150MB×3); 降 batch 后 200 步 × 2.11 s/step = 3670s, rc=0。
**跑完整链前先 `nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader` + `ps -p <pid> -o etime=,args=` 认人**。

## 3) ⚠️ A/B 两臂指标逐位相同 → 先怀疑判据, 不是模型

换模型指针做 A/B 时, 若关键指标**完全相同**(如 `conf 2.709 = 2.709`), 多半是**被换的东西没进驱动路径**。
实测: `pipeline_closure_run.py --vote` 下驱动信号是 `node.unified`(backbone), 被换的 INTACT 只是**投票 peer**
→ 换权重对结果零影响; 这组数字只能得出"未证明提升"。

隔离三件套:
1. **只改一个变量**(所有环境变量其余项固定: RUNTIME/DEVICE/KEEP_INPUT/STABLEWM_HOME/LOCAL_DATASET_DIR/MUJOCO_GL);
2. **确认它在驱动路径上** —— 用"该组件单独驱动"的入口(`SS_L4_INTACT=1` 时 INTACT 即驱动信号)做对照,
   而不是把它塞进 vote/融合里;
3. **≥3 seeds**, 且单 seed 差异 < 实测抖动幅度时既不许宣称提升也不许断言回退(本例同一策略跨轮 0.4 / 0.8 mm, ±0.4mm)。

部署门槛(用户口径): **提升才动默认档指针**(如 `intact_l4_current` 软链); 持平/回退一切照旧 = 零风险。
新 ckpt 目录要能被加载器认: 内**恰好一个 `weights.pt`**(软链到实际权重) + `config.json`。

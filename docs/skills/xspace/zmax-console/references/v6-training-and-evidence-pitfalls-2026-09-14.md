# v6 记忆条件 INTACT · 训练/取证坑清单 (2026-09-14)

配套文件: `references/l4-skill-ctx-and-layer-evidence-2026-09-14.md` (skill_ctx 契约 / 分层三格取证 /
共跑命令 / v6 判闸口径)。**本文只列本次实战踩到的坑, 与 SKILL.md 的「🧠 v6」段落互补。**

> 为什么单独开一个文件: 想把这几条并进 SKILL.md 的 v6 段落时, `skill_manage(action='patch')` 被
> read-before-write 守卫挡住 (`skill_view(name)` 因 dedup 返回 `content_returned:false`,
> `skill_view(name, file_path='SKILL.md')` 返回全文也仍被拒)。**建议 curator 下次整理时把本文并入
> SKILL.md「🧠 v6」段落的坑清单。** 本文件会自动出现在技能的 `linked_files` 里, 检索不会丢。

## 坑 1: 阶段轨迹不能读 `sim.stage_hist` (实测恒空)
统计「L3 扩展段 (插入/拔出/AOI转移/AOI检测/回程/放下) 走全了没」时读 `sim.stage_hist` → 恒为空 →
覆盖率误报 0/6 (功能其实走全了, 视频里能看全链)。正解 = 挂帧 sink 逐帧收:
```python
stages = []
def _sink(s, act, o, _st=stages):
    try: _st.append(str(s.sched.stage()))
    except Exception: pass
sim._frame_sink = _sink
tr = sim.run(max_steps=..., cap=...)
```
**通用: 向用户证明「某条链走完了」时, 从帧 sink 取阶段序列, 别信聚合属性。**

## 坑 2: 不需要模型的证据轮不许被模型拖死
`INTACT_POLICY` 不设 → 适配层回落**论文 HF 资产 (paper 运行时)** →
`InstantiationException: Error locating target 'module.InverseTransitionActor'` (paper 运行时没有这个类)。
于是「只要解析链/抗干扰视频、不跑模型」的证据轮被模型初始化失败整轮拖死 (exit 3)。
修法两条: ①桥 `--model-episodes -1` 时模型未就绪**只记 `model_skip_reason` 继续跑**;
②跑本域权重必须显式 `INTACT_POLICY=<ckpt>` + `INTACT_RUNTIME=root`。
另: 证据视频名带上档位 (`..._解析链_{cap}_seed{n}.mp4`) 免得 l3/l4 视频混在一起。

## 坑 3: 闭环反归一化 stats 必须与训练同一份 h5 现算
桥 `--stats` 指向 A 数据集的统计却去反归一化 B 数据集训的权重 = **静默量纲错误** (动作整体缩放/偏移,
视频表现为"乱走", 不报错、无告警)。一律 `tools/action_stats_from_h5.py --h5 <训练 h5> --action-space u
--out reports/<同名>_action_stats.json` 现算; 冒烟权重用它自己那套, 全量 v6 用 `optical_insert_v5_action_stats.json`。

## 坑 4: Hydra / 数据集加载四件套
- 配置里**不存在的键**必须 `+` 前缀: `+trainer.limit_train_batches=6` (直接写 → Hydra 报
  "To append to your config use +…")。
- `prefetch_factor` 只在 `num_workers > 0` 时合法 → `num_workers=0` 时带上它就
  `ValueError: prefetch_factor option could only be specified in multiprocessing`。
- `swm.data.load_dataset(name, cache_dir=...)`: `cache_dir` 是 **datasets 目录的父目录**
  (`<cache>/datasets/<name>`), 且 `name` 要带 `.h5` → 否则
  `FileNotFoundError: Cannot resolve '<name>': not a local path or HF repo id.`。
- 训练侧 `intact_forward(self, batch, stage, cfg)` 的 `stage` 实测是 **"fit"/"validate"/…**, **不是 "train"**;
  按 `stage == "train"` 写的打印/断言永不触发 (本次冒烟因此没打出 `[skill]` 行)。
  通道消费证据改看 `log_dict` 里的 `skill_ctx_used` (进度条显示 `fit/skill_ctx_used: 1.000`)。

## 坑 5: 「共同运行」的证据形态 (别去翻内部张量)
同一帧日志里同时出现 **模型 u / L2 场 u / 合成 u + `技能=SKxx w=..`** 即共同运行;
再补上 **「每帧真推理 N 次且 0 错误」** —— 对自带 skill 通道的 ckpt, 这一条**等价于**「skill_ctx 每帧都送到了」,
因为 `jepa.get_action` 有硬闸 (`skill_dim>0` 缺 `intr["skill_ctx"]` → 直接 ValueError, 不许静默降级)。

## 坑 6: 改采集口径后必须重采, 首 part 落盘就验
第一版 v5 采集跑完 part00 (1.44GB / 600 窗口 / 日志全绿) 其实**整列 skill_ctx 缺失** (4 元组解包坑被
`_frame_sink` 静默吞掉), 只能删档重跑 (白跑 ~20 分钟)。**首 part 一落盘就验三样**:
keys 里有 `skill_ctx` · 帧 std > 5 (真图) · `meta.ep_jitter` 有真值 (干扰真注入了), 别等全量跑完。

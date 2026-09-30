# 哨兵前提核对 + 「缩短训练」的量级/ETA 换算 (2026-09-14 夜实测)

> 应挂到本技能 SKILL.md 的「变体: 早收型哨兵」下 (第 4/5 条纪律) 与「坑」表。
> 同批背景: 判闸口径换代 v3→v4 见 `robot-policy-eval-pitfalls` §⑯ / `references/judge-caliber-v4.md`。

## 一、哨兵「前提已死 = 永久静默」(最隐蔽的失效模式)

哨兵是**条件成立才动**, 不是"守着就一定动"。前提(被监督的训练/流水线)一死 —— 关机、崩溃、主动停 ——
哨兵与"还没出新 ckpt"**完全不可区分**, 会一直挂机、一条不报, 看着像一切正常。

本次实况: 机器 17:36 关机 → 22:05 开机 (4.5h)。开机自检时看到 14 条 cron 全部 `last_status=ok`,
其中 4 条是围着 v6 记忆条件链的判闸/早收哨兵 —— 但它们等的训练在关机时就断了, 之后再没新 epoch。
另有两条更早的形态: v9 训练监视器早已判 DONE (前提永久满足, 白占一条 job);
v10 足量训练哨兵每 30 分钟巡检一个 09-12 就结束的训练。

**开班自检清单 (开机 / 接手长跑项目时逐条核对, 别把静默读成无事)**:

```bash
uptime; last reboot | head -3; last -x shutdown | head -3     # ① 是否刚重启/曾长时间关机
ps -eo pid,etime,cmd | grep -Ei "train|pipeline|autopilot" | grep -v grep   # ② 前提进程还在吗
# ③ 每条哨兵的前提核对: 它等的产物/进程是否可能再出现
ls -lt <产物目录> | head        # 产物最后写入时间 = 这条链还活着吗
```
- 前提已消失 → 在自检结论里**点名** (撤掉 job, 或写"待前提恢复"), 不要留在列表里当"正常"。
- 结论要给用户**可判定的一句话**: "没有训练在跑 (GPU 0MiB); 4 条 v6 哨兵的前提已消失, 要撤还是等?"

## 二、用户说「缩短训练 / 只跑 1 个 epoch 行不行」时怎么答

**先把步数与单轮时长算出来, 再答** —— 否则用户按错的数量级做决定。

```
train_clips ≈ 总帧数 − span × 回合数          # span = num_steps × frameskip
steps/epoch = ceil(train_split × train_clips / batch_size)
单轮时长    = steps/epoch ÷ 实测 it/s          # Lightning 进度条: [Epoch 0/12] step 200/5870 (2.1 it/s)
```

本次实例 (INTACT 光模块 v6r11): 149,100 帧 / span=16 / 2,982 回合 → 训练集 ≈ 91,250 clip
→ batch=16 → **5,870 步/轮**, 实测 2.1 it/s → **单轮 ≈ 47 分钟** (12 轮 ≈ 9.3 小时)。
⚠️ 用户会把"1 epoch"想成"10 分钟"——**实测差了近 5 倍**, 报 ETA 必须带这个换算。

**还要把「缩短后的量」与「已经拿到的量」对比**: 本次 1 轮 (5,870 步) ≈ 之前接力链累计额外步数
(r5→r10 = +5,000 步), 所以单跑 1 轮大概率是**复现同级, 不是台阶提升** —— 明说, 不要让用户以为省下的
是"重复劳动"。

**决策模式: 上限照设 + 早停按证据收** (替用户省掉"够不够"的赌博):
- `trainer.max_epochs=12` 照起, 同时**挂早收哨兵**: 每轮落 ckpt → 判闸 → 三连全过即自动停训出结果。
- 第 1 轮 47 分钟就有第一份判闸数字; 过闸 → 等效"1 epoch 收工"; 不过闸 → 自动续下一轮 (每轮一个 ckpt,
  中途关机只损失最后一轮)。
- 起跑后**当真验证在跑**: 进度行 + `nvidia-smi` + 首轮反向自检 (`✓ all tracked parameters received
  gradients on the first backward pass` —— 顺带证伪"新分支零梯度死锁")。

## 三、换判闸/换实现时, 下游读取的标记 schema 必须逐字不变

早收哨兵只读 `judged/<fam>_epoch{n}.json` 的字段
(`mae_on / mae_zero / const / std_ratio_on / win_const / skill_gain / no_collapse / verdict`) 与兼容别名
`v6_epoch_{n}.json`。本次判闸 v3→v4 换脚本时:
- ✅ 保留字段名与别名 → 早收哨兵零改动
- ❌ 手写别名时把 `v6_epoch_{n}` 写成 `v6_epoch{n}` (漏下划线) → 下游读者读不到新数字
- ✅ 旧口径标记改名 `*__v3superseded.json` 留证 (原始证据 json 原样保留在 reports/), 新旧数字**不混排**
- ✅ 干跑一次换后的哨兵, 确认"标记已存在 → 完全静默"再交给 cron

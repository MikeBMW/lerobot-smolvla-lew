# 「加量」为什么无效 + 训练取证陷阱（2026-09-25 同会话三次实测）

## 一、三条实测：**盲目"加大"都不增效**（同口径留出集）

同一任务、同留出集、同增强、同 batch，只改一个变量：

| 变更 | 结果 | 判定 |
|---|---|---|
| 步数 2500 → **8000**（3.2×）| best 0.009 vs 0.008（best 出现在 4500，之后过拟合）| ❌ **无益** |
| 数据加入**异构域帧** | 0.016 vs 0.008 | ❌ **拖同域** |
| 变体谱 5 维 → **8 维**（加偏航/槽位/表面随机）| 0.011 vs 0.010（对基线 0.013 仅 +15%，未达 ≥25% 目标）| ❌ **拖同域** |

**共同机理**：**同域留出集只会因数据分布更分散而更难拟合**。
"加时长 / 加异构数据 / 加随机维度"三者都在**稀释同域拟合**，换不来同域 MAE 的改善。

**结论（可复用）**：
- 训练增益的瓶颈通常**不在时长** —— 先把步数拉到"best 出现点"再往上加是浪费。
- 异构/增广数据的价值在**跨域鲁棒性**，**必须换指标验收**（带扰动的闭环/扰动档评测），
  拿无扰动的同域 MAE 给异构数据判死刑 = 用错指标误杀。
- 有效杠杆是**按能力缺口定向造数据**（先测出哪个子能力/哪一段是瓶颈，再针对它造样本），
  不是无差别加随机。
- **报告纪律**：这三条都要报"未达成"，把"加量无效"写成结论，别把 +15% 说成成功。

## 二、声明的随机化必须验证**真的到了仿真里**

**症状**：造数据脚本参数表写着 `goal_dy ±20mm / 力档 / 速度档`，看起来在域随机化。
**真相**：脚本只用了 `Env(seed=...)`，那些维度**只写进了标签，根本没注入引擎** ——
"5 维变体谱"有一半是名义上的。

**修**（以 MuJoCo 为例）：拿 free joint 直接改初始位姿 + 四元数，再 `mj_forward`：

```python
def apply_variant(sim, d):
    import mujoco as mj, numpy as np
    m, dt = sim.env.model, sim.env.data
    adr = None
    for i in range(m.nbody):
        if m.body(i).name == "peg":
            j = m.body_jntadr[i]
            if j >= 0 and m.jnt_type[j] == 0:        # 0 = FREE
                adr = m.jnt_qposadr[j]
            break
    if adr is None: return False, "未找到 free joint"
    p0 = dt.qpos[adr:adr + 3].copy()
    dt.qpos[adr + 0] += float(d.get("goal_dx", 0.0))
    dt.qpos[adr + 1] += float(d.get("goal_dy", 0.0))
    dt.qpos[adr + 2] += float(d.get("goal_dz", 0.0))
    yaw = np.radians(float(d.get("yaw_deg", 0.0)))
    q = dt.qpos[adr + 3:adr + 7].copy(); dq = np.array([np.cos(yaw/2), 0, 0, np.sin(yaw/2)])
    w1,x1,y1,z1 = q; w2,x2,y2,z2 = dq
    dt.qpos[adr+3:adr+7] = np.array([w1*w2-x1*x2-y1*y2-z1*z2, w1*x2+x1*w2+y1*z2-z1*y2,
                                     w1*y2-x1*z2+y1*w2+z1*x2, w1*z2+x1*y2-y1*x2+z1*w2])
    mj.mj_forward(m, dt)
    return True, "Δpos=%.1fmm" % (float(np.linalg.norm(dt.qpos[adr:adr+3]-p0))*1000)
```
**验收（必须做）**：跑 4 个变体，打印每变体**首帧观测**里代表位姿的维度 —— 数值必须
**逐个不同**（实测 `[0.157,0.521] / [0.093,0.690] / [0.058,0.519] / [0.135,0.617]`）。
只打印"✅ 注入成功"不算证据，要看**状态真的变了**。

## 三、实时进度：**别让进度粒度绑在日志的 `--stats` 上**

**症状**：控制台进度条 80 秒才跳一次（`--stats 250` → 250 步才一行日志）
→ 用户认定"进度条是假的"。

**修**：训练脚本每 N 步（实测 10 步）单独写**进度 JSON**，与日志解耦：
```python
if a.progress_file and (s % max(1, a.progress_every) == 0 or s == 1):
    json.dump({"step": s, "total": a.steps, "pct": round(100.0*s/a.steps, 1),
               "loss": round(float(L.item()), 6), "sps": round(s/max(1e-6, time.time()-t0), 2),
               "best_obs": (...), "ts": time.time(), "pid": os.getpid(), "running": True},
              open(a.progress_file, "w", encoding="utf-8"))
# 结束时再写一次 running=False / pct=100
```
前端只读这个文件 → **真实步数驱动**，粒度自己定。

### 两个把这条路堵死的坑（都踩过）
```
① **目录不存在** → open() 抛 FileNotFoundError → 被自己的 `except Exception: pass` **静默吞掉**
   → 进度文件从未生成，前端"无数据"，而日志一切正常，极难查。
   修: 启动时 os.makedirs(os.path.dirname(os.path.abspath(pf)), exist_ok=True)
       且**不要静默**: 首次失败打印一次原因, 之后静默。
   ★ 规则: 后台/可选路径的 except 也要**至少打印一次**, 否则等于埋雷。
② **参数没被脚本接受** → UI 下发了 `--progress-file` 但训练脚本没定义该参数
   → 进程**立刻** `unrecognized arguments` 退出，表面看是"点了没反应"。
   ★ 规则: UI 下发的每个参数, 都要在被调脚本上 `--help | grep` 验证存在。
```

## 四、取证：「是不是真在训练」必须用**同一条链**证明

用户会（合理地）怀疑"你说是真训练，凭什么"。要一次性给**环环相扣**的证据：

```
① 启动方式: 通过真实入口(UI API/CLI)启动, 记下返回的 jid + pid
② **真 CUDA 进程 pid**: 从 nvidia-smi 自己的进程表取, 而不是从 ps/启动返回值取。
   ★ 启动返回值常是 `/bin/sh -c ...` **包装进程**, 真 python 是它的**子进程**
     → 直接拿返回值去 GPU 表里找会 0 命中, 得出"证据不足"的**假阴性**。
   修: 优先在 GPU 表内按 cmdline 关键词匹配真训练进程; 否则 pgrep -P 取子进程。
③ /proc/<真pid>/cmdline: 证明是训练脚本, 且参数来自 UI 模板
④ 双源印证 + 递增性: 进度文件 step 与日志 step 相互印证, 且随时间**单调不减**
   ★ 两源**粒度不同**(进度 10 步 / 日志 250 步)时, 别按"逐点相等"判 —— 必然假失败。
     正确口径: 「日志 step ≤ 进度 step」+「在日志刷新点上两者精确相等」。
⑤ 硬件同步跃迁: 采样时打印 GPU 利用率/显存, 应看到 **0% → 100%**、显存**数百 MB → 模型量级**
```

**判据的反面**：任何"只在某种退化情形下才失效"的指标都不能当判据。
（见 `mixture-of-experts-architectures` 的 ④ 假阳性案例。）**先问"什么情况下这个指标会骗我"**，
再决定信不信它。

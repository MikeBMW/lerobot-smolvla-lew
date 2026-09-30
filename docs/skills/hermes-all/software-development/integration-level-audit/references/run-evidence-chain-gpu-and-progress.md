# 运行证据链：「真的在跑」怎么证（2026-09-25 增补）

> **权威增补**。SKILL.md 正文因受保护无法直接改，本文件是这一节的正式归属。
> 与正文同等效力。冲突时以本文件为准（下节规则已现场检验）。
> 适用：用户追问「**是真在 GPU 上训练么 / 进度是不是真的 / 真跑起来了么**」，
> 或你要在汇报里声称"任务真的在执行"之前。

## 1. PID 必须从设备表解析，不能信启动时拿到的那个 PID

启动命令返回的往往是 **shell 包装进程**（`/bin/sh -c ...`）或 `timeout ...` 包装进程。
它 `ps` 可见，但**不在** `nvidia-smi --query-compute-apps` 表里 → 采样脚本得出
「PID 不在 GPU 表 → 没在 GPU 上跑」的**假阴性**。

```bash
# ❌ 只信启动返回的 pid
nvidia-smi --query-compute-apps=pid --format=csv,noheader | grep -w "$LAUNCH_PID"   # 永远匹配不到

# ✅ 从设备进程表反查真训练进程（按 cmdline 匹配）
for p in $(nvidia-smi --query-compute-apps=pid --format=csv,noheader); do
  tr '\0' ' ' < /proc/$p/cmdline | grep -q 'joint_unified_backbone\|stage_moe' && echo "真进程: $p"
done
# ✅ 或取包装进程的子进程
pgrep -P "$LAUNCH_PID"
```
**实测：两个不同的采样脚本各踩一次**（一个 GPU 证明器、一个"APP 是否真训练"证明器）——
不是偶发，是这类脚本的**结构性问题**。写检查清单，别靠记性。

## 2. 进度必须由生产者细粒度写出，不要从粗粒度日志里刮

训练脚本 `--stats 250` 时，日志约 **80 秒**才出一行 → UI 进度条 80s 跳一次
→ 用户直接判定「**进度是假的**」（即使它确实是真数据）。

**修法（与 `--stats` 解耦）**：生产者每 N(=10) 步写一个 progress JSON。
```python
if a.progress_file and (s % max(1, a.progress_every) == 0 or s == 1):
    json.dump({"step": s, "total": a.steps, "pct": round(100.0*s/a.steps, 1),
               "loss": round(float(L.item()), 6), "sps": round(s/max(1e-6, time.time()-t0), 2),
               "best_obs": ..., "ts": time.time(), "pid": os.getpid(), "running": True},
              open(a.progress_file, "w", encoding="utf-8"))
# 收尾: 写 running=False + pct=100（否则 UI 永远显示"还在跑"）
```
UI 侧读该文件，并带 `age_s` + `stale`（超 30s 未更新 → 标"已停"）。

**两个必踩的坑**：
- 写前必须 `os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)`
  —— 目录不存在时 `FileNotFoundError` 被 `except: pass` **静默吞掉**，
  表现为「代码明明在、文件就是没有」。**禁止裸 `except: pass` 吞写失败**，至少打印一次原因。
- 日志与进度文件**粒度不同**（250 vs 10）—— 比对判据见下节。

## 3. 判据本身要先被证伪，再信它的"通过"

同一会话里两头都栽过，**这类错误比代码 bug 更贵**（会把结论带反）：

| 错法 | 现象 | 正确口径 |
|---|---|---|
| **弱判据 → 假通过** | 指标只在"某个类占满"时才失效；一旦某专家/某类吃掉全部样本，该指标**自动全通过**，而模型已退化 | 换成**单射性**式判据：要求各类映射到**不同的**目标（见 `mixture-of-experts-architectures`） |
| **错粒度比对 → 假失败** | 两源粒度不同（10 步文件 vs 250 步日志）却**逐点要求相等** → 永远不相等，判"不一致" | 细粒度值 **≥** 粗粒度值，且在粗粒度**刷新点精确相等** |

**口诀：一个只在"某类独占"时才失效的指标，等于没有指标。**
工具修好后要**重跑**并把修正前的结论**撤回**（本次撤回了一条"分化成立"的结论）。

## 4. UI 不许出现 null / undefined / 占位

每个字段给**实测值**，或给**明确说明文本**（不能留空）：
```
❌ power_limit_w = None          → 面板显示空/undefined
✅ 三级回退查询 (power.limit → power.default_limit → enforced.power.limit)
   仍无 → "本机 GPU 不报功耗上限(笔记本)"   ← 明确说明, 不是空
```
**"未测到"与"实测为 0"必须可区分**：约定未测到 = `-1.0`，0 是合法实测值（GPU 真空闲）。
把缺数据写成 0，下游会把"没数据"当"真的零负载"。

## 5. 三合一才是铁证（单一证据都会被反驳）

```
① 设备进程表里有**真 PID**（不是包装进程）
② 利用率/显存/温度 **时间序列**（连续采样，不是一次快照）
③ **步数推进**（来自日志或进度文件）
```
- 只看「利用率 100%」→ 可能是别的进程占着卡
- 只看「步数在涨」→ 可能在 CPU 上跑
- 三者同时看，才既证明"在跑"又证明"跑在设备上"

**冷启 → 训练的跃迁本身就是好证据**：缓存加载期 `GPU 0% / 显存 340MB / 57°C`
→ 训练开始后 `GPU 100% / 1629MB / 68°C`。这个台阶比静态数字更有说服力。

## 附：一次实测的正确输出形态（可直接仿写汇报）

```
① APP 启动: 包装 pid 210094 → **真训练 pid 210095**（按 GPU 表 cmdline 匹配）
② 真 pid 在 nvidia-smi 进程表: ✅（3s 后出现）
③ cmdline = 训练脚本 + 启动方下发的参数: ✅
④ 双源同源（日志 ≤ 进度 且 边界相等）: ✅（窗口内无 250 步刷新点 → 边界样本为空属正常）
⑤ 进度单调递增: ✅ [1, 30, 70] · GPU 100% / 1629MiB / 66-68°C
```

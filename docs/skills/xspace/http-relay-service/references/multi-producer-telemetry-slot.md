# 多生产者遥测 + 单槽 `/latest`：互相顶掉（2026-09-25 实测）

补 SKILL.md §1「Queue semantics」——§1 讲的是 **pop 队列**（取走即删），
本条讲的是**另一种更隐蔽的语义**：只留最新一个包（覆盖式），
**多台机器各自上报同一类遥测时互相顶掉**。

---

## 症状 vs 真相

```
症状：大屏/APP 上「某台机器 一直显示 等待上报」
真相：两台上报**都成功**了，只是 /latest 是单槽位 → 谁最后传谁获胜
```
所以**不要**因为「页面显示等待上报」就去怀疑上传脚本挂了 —— 先验证上传是否成功
（看上传返回值 + 连续读 `/latest` 是否来回跳）。

## 30 秒判定：是单槽覆盖还是按 key 分槽？

```bash
for i in 1 2 3 4; do
  curl -s https://<domain>/api/relay/latest \
   | python3 -c "import json,sys;d=json.load(sys.stdin);m=d.get('meta') or {};print(m.get('source'), m.get('machines'))"
  sleep 3
done
```
- **来回跳**（`['4060','mac']` / `['mac']` / `['4060','mac']` …）→ **单槽覆盖**
- **稳定** → 分槽，或只有一个生产者

本轮实测（我方 6s 一次、对方 30s 一次）：
```
第1次 machines=['4060','mac'] ✅
第2次 machines=['mac']        ← 被对方的包顶掉
第3次 machines=['4060','mac'] ✅
第4次 machines=['4060','mac'] ✅
⇒ 3/4，即"时有时无"
```

## 缓解（治标 —— 必须对用户说明是治标，并给出根治选项）

### 1. 提高己方上传频率
6s 级 → 己方包成为「最新」的概率占优。
⚠️ **6s 级不适合 cron**（cron 最小 1 分钟粒度）→ 用**后台常驻进程** `--watch 6`。
低频链路（如每 2 分钟写 GitHub raw JSON）才挂 `no_agent` cron。**两条链路可并存**：
```
cron(2min)     → 保「零安装网页」那条链路
常驻(6s)       → 保「中转单槽」这条链路
```

### 2. 在自己包里顺带转发对方的真实值（关键技巧）
从 `GET /latest` 读出对方那一段，**原样**并入自己的包 ——
这样无论消费者读到谁的包，两台机器都在：
```python
mk, mv = fetch_other_latest()          # 读 /latest，按 backend/role 认出对方那台
machines = {"本机名": collect_mine()}
if mk:
    machines[mk] = mv                  # ★ 只搬运、不改一个数字
payload = {"meta": {"machines": list(machines.keys()), "time": time.time(), ...},
           "data": {"machines": machines}}
```

**红线（= 生产数据完整性）**：
```
只搬运、不修改对方的值；字段名/单位一律照抄。
若"多出来的字段"是自己算的（不是搬运来的）→ 绝不带 —— 那在生产视图里就是假数据。
```
判断问句：*这个包里多出来的字段，是不是别人采集、我只是搬运？*
是 → 可以带，且 `meta.machines` 要列全名单；否 → 不能带。

### 3. 根治
**服务端按生产者名分槽**存最新状态（改 relay 需要服务器权限）。
→ 明确向用户索要权限 / 请维护方改；
**不要默默用治标方案并宣称"已解决"**（用户会说"还是时有时无"）。

---

## 上报包格式（务必与已接入的对端对齐）

先 `curl /latest` 把对端的**实际包结构抄下来**再对齐，**别自己起名**。
本轮对齐到的格式：
```json
{"meta": {"source": "<来源>", "type": "hw_metrics", "project": "...",
          "role": "work|backup", "machines": ["<名>"], "time": 1790332908.2},
 "data": {"machines": {"<名>": {
    "host": "Macmini9,1 / Apple M1",
    "cpu":  {"cores": 8, "load1": 1.67, "load5": 1.79, "load15": 1.81, "percent": 21.1},
    "mem":  {"total_gb": 8.0, "used_gb": 3.0, "avail_gb": 2.1, "percent": 74.1,
             "swap_total_gb": 2.0, "swap_used_gb": 1.3, "swap_percent": 65.2},
    "disk": {"root": "/", "total_gb": 228.3, "used_gb": 133.7, "free_gb": 94.6, "percent": 58.6},
    "gpu":  {"backend": "mps|cuda", "name": "...", "util_pct": 0.0,
             "vram_used_mb": 340.0, "vram_total_mb": 8188.0, "vram_used_pct": 4.2,
             "temp_c": 43.0, "power_w": 9.9, "clk_mhz": 1890.0}}}}}
```

- 采不到的量给 **null**（消费端渲染「—」），**不要给 0**（0 是合法实测值，会误导）
- 上传成功判据：返回 `{"ok": true, "name": "pkg_<ts>.json", ...}`；失败/被限流要打日志
- 上传脚本建议支持 `--watch N`（常驻）与 `--once`（冒烟），并用 `--push` 之类区分"是否推远端"

## 相关

- 消费侧的完整排查表（没喂数据 / 页面无字段 / 通道被顶掉 / 装的是旧版）见技能
  `user-facing-dashboard-delivery` → `references/ui-locator-and-relay-slot.md`
- DDS 路线（替代 relay）见本技能 `references/dds-cyclonedds.md`

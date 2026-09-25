# 训练 + 部署 控制台（分层归属路由 · 零依赖单文件）—— 2026-09-25 落地

> 管**运维面**：谁训练哪层、怎么晋级、怎么留痕。与 CICD 流水线本体（采集→训练→部署）同读。

---

## 1. 分工即代码（不是注释）

```
老倪: "训练加部署控制; L2模型训练给小芳; L3以上微调训练给静静; Web你提供控制平台"

归属表（固化为策略, 平台按此**路由**）:
  L2 检测层   → **小芳（Mac 备份端）**  mode=remote → 平台**只生成处理单, 不越权本机执行**
  L3 调度层   → **静静（4060 工作端）**  mode=local
  L4 认知层   → 静静                    mode=local
  L5 规划层   → 静静                    mode=local
  MEM 记忆层  → 静静                    mode=local
```
★ 关键：`mode=remote` 的层，`POST /api/train` **返回处理单**（可复制给备份端执行），
**绝不在本机偷偷跑** —— 否则分工形同虚设，还会把工作端 GPU 抢掉。

---

## 2. 最小可用形态（标准库单文件）

```
tools/train_deploy_console.py   ← 只用 http.server + json + subprocess, 零依赖
  GET  /              HTML 看板（层卡片 + 归属徽标 + 操作按钮）
  GET  /api/status    各层: 归属 / 最新产物(名·MB·mtime·sha16) / 在役默认档 / 管道状态
  GET  /api/manifold  结构化流形 JSON
  GET  /api/audit     最近 12 条操作审计
  POST /api/train     {layer, steps} → local 起 job; remote 返回处理单
  POST /api/deploy    {layer, dir}   → 晋级默认档(sha256 + prev + 审计)
  --status            只打印状态 JSON 后退出（便于 CI 断言, 无需起服务）
```
不用 Flask：**零依赖 = 复制到任何机器都能起**, 不会因依赖漂移坏掉。

---

## 3. 三条硬约束（踩出来的）

```
① **部署必须留痕**: 每次晋级写 models/model_default.json(当前档)
   + docs/deploy_audit.jsonl(追加 {ev, layer, dir, sha16, prev, note, ts})。
   只记"当前是什么"不够 —— 没有 prev 就无法回答"从哪滚回来"。
② **晋级必须带 sha256**: 同名目录内容会变(实测: 两次训练产物 sha256 竟完全相同,
   因某个配置项静默未生效)。记录里没有 hash 就无法事后判定用了哪份权重。
③ **一台机器同时只跑一个加载模型的进程**: 起训练前检查是否已有 job 在跑。
   实测: 并发两个模型进程必触发内存限额 OOM（本机命令级 cgroup 限额约 8GB,
   与 free 显示的空闲无关）。
```

---

## 4. 与画布/CICD 共用同一真源

```
平台**不新造**状态文件: 读写 docs/PIPELINE_STATE.json（与画布高亮、CICD 控制台同一份）。
job 起停时更新 stages[层] = {status, ts, note} → 画布自动高亮当前执行节点。
⇒ 一个真源, 多个视图（画布 / 控制台 / APP）。别让平台自己维护一份状态。
```

---

## 5. 实测验收（全部真跑）

```
✅ 首页 HTTP 200 · 含流形面板
✅ /api/status: 归属表正确 + 各层产物列出
✅ L2 训练请求 → "已生成处理单(归属 小芳)" **未在本机执行**
✅ L4moe 训练请求 → 本机起 job + 日志 + 审计
✅ 部署晋级 → 写默认档 + sha16 + prev + 审计
```

---

## 6. 收尾清单

```
□ local/remote 路由分支真的分开（remote 层不许在本机起进程）
□ 部署留 prev + sha16（能回滚、能追溯）
□ 状态读同一份 PIPELINE_STATE.json, 不另造
□ 未接入的层（如 L5 未接 LLM）在看板上显式标注, 不伪装成"在工作"
□ 监听地址配白名单（只允许指定机器访问），与对外服务同策略
□ --status 一次性模式（CI 可直接断言, 不必起服务）
□ 大文件(权重)不进 git; 交付走网盘/中转 relay
```

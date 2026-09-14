# VSCode debugpy 配置卫生 · ③ 的最终处置 (2026-09-13 实录)

老倪原话：**「这是你给我写的，不好使，为什么要放在这？当时为什么写这个」**
→ 这类追问的标准应答姿势与处置范式，记在这里防止重犯。

## 1. 犯了什么错
`③ 根运行时 · 官方 eval (repo 自训权重, direct)` 是我当时**从 ② 复制粘贴**写进去的：
```jsonc
// ③ 的 args —— 名字说"repo 自训权重"，参数却是论文权重，自相矛盾
"program": "${workspaceFolder}/eval.py",          "cwd": "${workspaceFolder}",   // 根运行时
"solver=direct", "policy=recovery_delta_full_pusht_s3072",                        // ← 论文权重 (错)
```
后果：论文权重 config 要 `module.InverseTransitionActor`，根 `module.py` 没这个类
⇒ `InstantiationException: Error locating target`，**该配置从诞生到删除一次都没跑通过**
（判据：预期产物 `/home/ubuntu/stable-wm-cache/debug_root_pusht.txt` 根本不存在）。
更糟的是我自己写的 `DEBUG_VSCODE.md` 表格第 11 行明明写着「③ = repo 自训权重用」——
意图写对了、args 写错了，属于自相矛盾，不能拿"当时是这么设计的"当解释。

## 2. 处置范式（用户选了 B：直接删，不留半成品）
```
① 备份           /home/ubuntu/l4_ab/backups/del_cfg3_20260913/{launch.json,DEBUG_VSCODE.md}
② 删配置块       .vscode/launch.json 里删掉 ③ 整块；「④ 当前打开的文件」顺位改名 →「③ 当前打开的文件」
                 （不留空号，否则 F5 列表看起来还像少了一个能用的配置）
③ 同步文档       DEBUG_VSCODE.md：表格删该行 · 表头「4 个配置」→「3 个配置」·
                 表下加「已删除 + 原因」引用块 · 顺手修旧路径 tools/intact/… → /home/ubuntu/l4_ab/…
④ 自证            python -c json.load 合法 & 配置数=3；逐字段 diff 证明 ①/② 完全一致、④→③ 仅名字变；
                 grep "根运行时|④" 无残留（**故意保留**第三节那条硬前提「必须用 paper_runtime 的
                 module/jepa (InverseTransitionActor vs IntentActionActor)」——它是防复发的护栏）
⑤ 报告           只讲"改了什么 + 怎么证明没伤到能跑的"，不讲过程
```

## 3. 通用规则（下次写任何 debugpy/launch 配置照这个来）
1. 新配置 **必须真跑到 rc=0** 才算交付；没跑通的不许留在 launch.json 里（老倪判据就是"不好使"，他不读你的意图）。
2. `policy` / `--config-name` 必须与 `program` 的**运行时**匹配；
   自查 = 把 args 里的 policy 跟配置名对一遍，不一致就是坏的。
3. 删配置要顺位重命名 + **在文档里留「已删除 + 为什么」**，否则下一个我/下一个人会再造同样的坑。
4. 删/改前备份 + 用「JSON 解析 + 逐字段 diff」自证没伤到能跑的配置，不能只说一句"我删了"。
5. 被问"当时为什么写这个"时：先取证据（配置 args、自己写的文档、预期产物是否存在）→ **直接认错**说清是
   复制粘贴疏忽 → 给处置方案。**不要编造设计理由**，"诚实认账 + 立刻处置" > "事后找补"。

## 4. 遗留（未解决，别当成可用通路）
repo 自训权重（`checkpoints/intact_goal_zmax_*`）目前**没有可用评测配置**：③ 删掉后只剩 ②（只吃论文权重）。
要评自训权重要另起一个 `cwd=paper_runtime` 或显式 `sys.modules["module"] = paper_runtime.module` 的配置，
且仍需解决根运行时 `stable_worldmodel/policy.py:420` 的 `plan.reshape([2,25,-1]) vs size 80` 维度问题。

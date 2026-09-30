# 长任务等待纪律 + 归档交付 (2026-09-17 用户当场纠正)

## 1) ⛔ 等长任务期间**禁止 sleep 空转**

用户原话: 「为什么你总是 sleep 呢? 干什么呢? 不要 sleep 了」—— 训练/渲染/评测在后台跑几十分钟时,
`sleep 240 && tail 日志` 这类调用让用户看到的是"agent 什么也没干, 只在打盹"。

正确姿势:

1. **起任务时就带通知**: `terminal(background=true, notify_on_complete=true)`, 或接力脚本 + 哨兵 cron。
   完成通知会自己回到会话, 不需要你去等。
2. **等待期做实事** (没人催时最该做的): 写设计文档 / 把下一步要用的分析脚本先写好 /
   验证已产出的中间物 (标签 ↔ 画面一致性、数据规模、md5、测集自检) / 归档 / 更新技能 / 提交已完成的代码。
   实测一轮: 25 epoch 训练期间并行写完设计文档 + 分析脚本 + 反向验证 + 测集自检 —— 全是并行产出。
3. **要看进度就把"看进度"夹在干活调用里** (同一个 terminal/execute_code 里既做事又 `tail` 一眼),
   不要单独发一个 sleep 调用; 状态只在有实质新信息时才报给用户。
4. 需要"下一个 epoch / 下一批产物"才有意义时, 靠**完成通知**, 或下次干活时顺带看。
5. **合法的等待只有两种**:
   - 脚本内部 (`while pgrep -f ...; do sleep 60; done` 接力脚本; 见 `references/reboot-resume-and-eta.md`) ——
     sleep 属于流水线, 不属于 agent 回合;
   - **测量型取样** (Δ步/Δ秒 ETA): 同一命令里取样 → 等窗口 → 再取样并算出速率。目的是**产出数字**, 不是等结果。

## 2) 长流程落成脚本再跑 (别用巨型 inline 命令)

多阶段流程 (生成→组装→训练→评测→归档) 一律写成 `.sh`/`.py` 文件再 `bash <file>`:
可复跑、可留证 (`tee` 到日志)、失败可续跑; 巨型 inline 命令既难改又容易触发框架的载荷/解析限制被拦。

## 3) 归档交付件: 硬链接 + MANIFEST

用户说"保存数据"时, 同盘归档用 **`cp -al`(硬链接)** —— 数据集不重复占盘, 归档与工作副本同 inode:

```bash
A=~/zmax_data/<专题>/$(date +%Y%m%d); mkdir -p $A/{weights,evidence,frames,logs,scripts,dataset}
cp -a  <权重 + 训练记录(results.csv/args.yaml)>  $A/weights/     # 小文件直接拷
cp -a  <证据 json / 目检图 / 真机帧>              $A/evidence/    # 交付取证
cp -al <数据集目录>                               $A/dataset/    # ← 硬链接, 零额外占用
```

MANIFEST.md 必写 (未来会话只认它, 不认你的记忆):

- 结论一句话 + 结果表 (各臂/各档的真实数字)
- **权重 sha256** (证明归档就是当时测的那份)
- 数据规模 + `data.yaml` md5 + **重生成命令 (含随机种子)**
  —— 数据不可复现就失去归档意义; 可复现则不必拷贝, 记命令即可
- 复现评测命令 (评测器 / 分析器 / 验证脚本)
- **诚实缺口** (未验证项、被阻塞项、需要外部条件才能做的下一步)

⚠️ 报归档体积时说清"`du` 表观 vs `df` 真实": 硬链接后 `du -sh` 仍显示数据全体积, 但 `df` 不涨。

## 4) 关机前核查清单 (用户说"准备关机"时逐条给证据)

```bash
# ① 我的后台任务全结束了?          ② 常驻服务 active + enabled (开机自恢复)?
ps -eo pid,args | grep -cE "<我的脚本>";   for s in <services>; do systemctl is-enabled $s; systemctl is-active $s; done
# ③ 服务没有反复重启? (Restart=always 陷阱)
systemctl --user show <svc> -p NRestarts -p SubState
# ④ 资源 / 磁盘红线                ⑤ 没有任何未推送提交
df -h /; free -g; nvidia-smi;      git log --oneline origin/main..HEAD | wc -l
# ⑥ 临时验证目录已清 (省盘, 且下次不会读到旧结论)
```
逐条**带证据**汇报 (enabled/active、NRestarts=0、可用盘、未推送=0); 未提交的工作区改动要明说是什么
(例: GUI 拨钮状态 `src_state: 真机→仿真` 是用户在界面上的选择, 不是代码改动 —— 别顺手提交)。

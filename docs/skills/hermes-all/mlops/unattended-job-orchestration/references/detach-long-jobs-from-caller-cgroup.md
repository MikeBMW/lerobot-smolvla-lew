# 长跑任务别做启动者的子进程 (cgroup 连带杀) — 2026-09-18 实测

## 症状 (极易误判)

从桌面 GUI (PyQt 控制台) 里点按钮起的训练/长任务, 会在 GUI 退出后**静默死亡**:

- 训练日志**没有 traceback**, 断在某一轮 (实测: 100 轮的任务断在 epoch 51);
- `pgrep -f <训练脚本>` 查不到进程, GPU 显存立刻回落;
- 看上去像"模型/数据问题"或"训练脚本 bug" —— 本轮就是照这个方向排查了很久才回头查 cgroup。

## 根因

GUI 里 `nohup <cmd> > log 2>&1 &` 起的进程**仍在 GUI 那个 systemd 单元/会话的 cgroup 里**。
systemd 默认 `KillMode=control-group`: 单元主进程退出时, 会把**该 cgroup 里所有进程**一起
SIGTERM/SIGKILL。所以:

- 关窗口 / 重启控制台 / 控制台自身崩 → 训练一起没了;
- `nohup` 只挡 SIGHUP, **挡不住 cgroup 清理**。

判据 (一眼分清):

```bash
ps -o pid,ppid,etime,args -p <pid>     # ppid=1 或 ppid=<GUI pid> 都还在别人组里
systemctl --user status <unit>         # 真正独立的长任务应该是一个 --user 单元
systemctl --user show -p ControlGroup <svc>   # 看 GUI 单元的 cgroup 里挂了哪些进程
```

## 正解: 起成独立瞬态单元 (用户级, 不需要 root)

```bash
systemd-run --user --collect --unit <job-name> \
    --working-directory <repo> \
    bash -lc '<cmd> > <log> 2>&1'

systemctl --user status <job-name>          # 单元状态
journalctl --user -u <job-name> -f          # 输出 (也可只依赖 <log>)
systemctl --user stop <job-name>            # 需要时停掉
```

要点:

- `--collect`: 单元结束后自动回收, 不残留 failed 单元污染 `list-units`。
- **自我重入**: 脚本加 `--detached` 开关 —— 主进程只负责起单元并立刻返回,
  否则调用方 (GUI) 会阻塞等到长任务跑完, 按钮看起来"卡死"。
  实现要点: 用 `env <MARKER>=1` 标记子进程, 再拼接 `sys.executable + 脚本路径 + 原始 argv`
  (用 `shlex.quote`) 交给 `systemd-run`; 见 `tools/yolo_annot_train.py` 的 `--detached` 分支。
- `--working-directory` 必给: 瞬态单元默认 cwd 是 `/`, 相对路径会全部失效。
- 显式给环境变量: `-p Environment=KEY=VAL` (瞬态单元不继承调用者的 export)。
- 验收: 起单元后**重启/关掉启动方 (GUI)**, 再确认任务仍在跑且日志继续增长 —— 这才算独立。

## 同类适用

任何"从有 GUI / 有会话的进程里起的长活": 数据下载、评测批跑、常驻推理服务、定时抓取。
凡是需要"会话死了它还活着"的, 一律走独立单元 (或 cron), 不要靠 `nohup`/`setsid` 的心理安慰。

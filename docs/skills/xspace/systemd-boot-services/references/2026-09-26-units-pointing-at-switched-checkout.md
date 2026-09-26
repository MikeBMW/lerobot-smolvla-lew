# unit 引用的脚本必须落在"稳定路径"(2026-09-26 实事故)

## 现象

服务 `systemctl is-active` 一直是 `active`（跑了 23 小时）, 但**一旦重启就挂**:
```
ss-remote-tap.service: python3: can't open file '/repo/tools/ss_remote_tap.py': [Errno 2] No such file or directory
ss-remote-tap.service: Main process exited, code=exited, status=2/INVALIDARGUMENT
```
后果: 真机只读采集链断流（帧龄不再更新）, 而且**只有重启才暴露** —— 平时看 `is-active` 全绿。

## 根因

unit 里的脚本/挂载路径指向一个**会被替换的检出目录**:
```ini
ExecStart=/usr/bin/docker run ... -v /home/ubuntu/lerobot-smolvla-lew:/repo:ro ... python3 /repo/tools/ss_remote_tap.py
```
该目录被**并行工作线切到了另一个分支**(`mac-hw`), 那个分支里**没有** main 线的脚本 ⇒ 重启即失败。
同源受害的服务一次查出 **6 个**(采集/旁路/YOLO旁路/网络优化/web桥/飞书推送)。

## 修法（可复制）

1. **选一个稳定路径**: 关键服务统一指向 canonical worktree（如 `/home/ubuntu/zmax_rel`），
   不要指向"多人/多线共用的检出"。
2. **venv 也一起稳**: worktree 里没有 venv 时用软链复用（venv 与分支无关）:
   `ln -s /home/ubuntu/lerobot-smolvla-lew/gui-venv311 /home/ubuntu/zmax_rel/gui-venv311`
3. **逐个 unit 重指 + 备份 + 重启复核**（写成可重跑脚本, 别手改）:
   ```bash
   for s in ss-remote-tap ss-bypass ss-yolo-bypass zmax-net-optimize zmax-web-agent-bridge aoi-feishu-push; do
     sudo cp -n /etc/systemd/system/$s.service /etc/systemd/system/$s.service.bak
     sudo sed -i 's#/home/ubuntu/lerobot-smolvla-lew#/home/ubuntu/zmax_rel#g' /etc/systemd/system/$s.service
   done
   sudo systemctl daemon-reload
   for s in ...; do sudo systemctl restart "$s"; done
   sleep 20; for s in ...; do printf "%-24s %s\n" "$s" "$(systemctl is-active $s)"; done   # 复核 6/6 active
   ```
   **docker 容器型服务**要连 `-v <树>:/repo:ro` 挂载路径一起改（只改 ExecStart 不够）。
4. **端到端验证**: 看真实产物有没有恢复（本次: 采集 jsonl 的 mtime 回到当前秒, 帧龄 0s）, 不能只看 `is-active`。

## 踩过的坑

| 坑 | 现象 | 处置 |
|---|---|---|
| `is-active` 绿 ≠ 真健康 | 跑了 23h 的服务一重启就挂 | 验证要**真重启一次**再看 `is-active` + 产物 mtime |
| oneshot + `RemainAfterExit=yes` | `systemctl start` 无输出、日志不追加 | 必须 `systemctl restart`（start 认为它已在运行, 不重跑） |
| 脚本无执行位 | `status=203/EXEC` | `chmod 755 <脚本>` |
| 服务以 root 跑 | 在仓库 `reports/` 写 root 属主文件 → 用户态工具再也写不动 | unit 加 `User=ubuntu` + `Group=ubuntu` |
| 停掉容器型采集器 | 旧进程可能加载的是**已被切走的分支**上的代码, 停了就起不来 | 停之前先确认 unit 指向的路径里脚本**确实存在** |
| 内联长命令 | hardline blocked | 写成 `/tmp/xxx.sh` 再 `bash` 跑 |

## 预防

- 给这类服务加**一条周期性自检**: 断言 unit 引用的每个脚本 `-f` 存在, 缺了立刻报警（比等重启便宜得多）。
- 多线并行开发同一台机器时, **各线独立 `git worktree`**, 不要把两套工作流塞进同一个检出目录。

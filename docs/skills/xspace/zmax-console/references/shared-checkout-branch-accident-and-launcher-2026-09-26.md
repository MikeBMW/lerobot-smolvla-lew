# 共享检出被切分支 → 「画布加载失败 / 点图标起旧 GUI」事故处置 (2026-09-26 实测)

## 0. 症状 → 先怀疑"树被换了", 别先怀疑代码

用户报「状态空间模型画布加载失败」时的真实根因链:

```
运行中的控制台来自 /home/ubuntu/lerobot-smolvla-lew
  └─ 该目录已被**并行 APP 线切到 mac-hw 分支** (两线共用一棵 checkout)
      ├─ 该分支没有 flows/  → 画布加载 (只拼 <仓库根>/flows/state_space_obs.json) 直接失败
      │    → 弹「状态空间模型画布加载失败」
      └─ 该分支的 studio.py 还是**旧版** (665KB/v5.6.0 vs main 808KB/v5.15.7)
           ⇒ 用户点的其实是旧控制台
桌面启动器 XSpace-Studio.desktop 的 Exec 硬编码指向那棵树 → 点图标必踩
```
**判据(3 条命令定位)**: ① `ps -o args -p $(pgrep -f "studio.py")` 看解释器/路径 ②
`ls <那棵树>/flows` 有没有画布真源 ③ 比对 `grep -oE "Z-MAX v5\.[0-9.]+" <树>/tools/gui/studio.py` 版本号。
> 教训: 同一台机器上多个 agent 线共用一个 checkout 时, "文件消失/版本回退/服务起不来"这一族症状,
> **先查当前分支与哪棵树在跑**, 再查代码。

## 1. 修法 A: 路径解析改多候选 (谁在跑都能找到真源)

```python
def _flows_path(name):
    """flows/ 真源多候选定位: env > 本检出 > main worktree > 默认检出 > 打包 _MEIPASS"""
    if getattr(sys, "frozen", False):
        cands = [os.path.join(getattr(sys, "_MEIPASS", "") or "", "flows", name)]
    else:
        cands = [os.path.join(_repo_root_path(), "flows", name),
                 os.path.join("/home/ubuntu/zmax_rel", "flows", name),          # main 线 worktree
                 os.path.join(os.path.expanduser("~"), "lerobot-smolvla-lew", "flows", name)]
    env = os.environ.get("ZMAX_FLOWS_DIR") or os.environ.get("ZMAX_FLOWS")
    if env:
        cands.insert(0, os.path.join(env, name))
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return cands[0]        # 零回退: 找不到仍返回原路径, 失败行为与以前一致
```
把它接到所有"画布/库/模板"加载点 (`_load_state_space_library_group`、打开状态空间画布、cicd_workflow 等)。
**取证** (`tools/verify_canvas_load_fix.py`, 8/8): 把 `_repo_root_path` monkeypatch 成"没有 flows 的那棵树" → 断言仍命中真画布;
再断言画布 JSON 真加载(节点/连线数 + 关键节点在位) + env 覆盖生效。

## 2. 修法 B: 启动器/服务别写死检出路径

- `tools/gui/launch_studio.sh`: `GUI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"` +
  `REPO_ROOT="$(cd "$GUI_DIR/../.." && pwd)"`, 解释器在 `$REPO_ROOT/gui-venv311/bin/python` 与旧路径间取第一个可执行的。
- 两处 .desktop (`~/Desktop/`, `~/.local/share/applications/`) 的 `Exec=` 指向**main worktree** 的 launcher;
  改前 `cp -n` 备份。
- 服务 unit 的 `ExecStart`/`-v` 挂载同样要指到有代码的那棵树; 若目标树缺 venv, 软链过去
  (`ln -s <有venv的树>/gui-venv311 <worktree>/gui-venv311`)。
- **运行时产物(非 git)** 互补问题: main worktree 常缺 `runs/`(YOLO 权重) `outputs/` `data/` 里的大文件 →
  把这些**逐个软链**进 worktree (目录级 ln -s + 缺件逐个补), 这样"代码/画布在 worktree, 大产物只有一份"。
  实测: runs 800M · outputs 16G · models 缺 23 件 · data 缺 52 项补齐后控制台可正常运行。
- **端到端验证**: 用启动器起 → 断言进程 `readlink /proc/<pid>/cwd` 在 target 树 · 实例数 1 · 启动日志 0 Traceback。

## 3. 同源风险清单 (切分支时一起断的)

| 现象 | 根因 | 处置 |
|---|---|---|
| 6 个在役服务重启即 `FileNotFoundError` | unit 指向的脚本在另一分支不存在 | 重指 main worktree + `tools/fix_services_to_main.sh` 一键复现 |
| 采集链断流 (帧龄不再刷新) | 同上(容器 `-v <repo>:/repo` 挂了空树) | 同上; 重启后核对 jsonl mtime 回到 0s |
| 桌面图标起旧 GUI | .desktop Exec 硬编码 | §2 |
| 画布加载失败 | flows/ 不在当前树 | §1 |

## 4. 两条线的长期解法 (建议, 需用户点头)

- 每线独立 `git worktree`(main 线留在原目录, 其它线另开目录), 避免"共用一棵树"互相踩。
- 服务/启动器**一律不写死 checkout 路径**, 用"launcher 自身位置推导 + 多候选回落"(§1/§2)。

## 5. 相关技能
- 主线程阻塞 I/O → 界面卡顿的度量与修法: `pyqt5-gui-development`
  (`scripts/ui_jitter_probe.py` · `references/periodic-timer-blocking-io-worker-thread-2026-09-26.md`)
- 字体可读性反馈「太小」: 一次到位放大 + 给 pixelSize/行高客观口径 (同技能 §14)

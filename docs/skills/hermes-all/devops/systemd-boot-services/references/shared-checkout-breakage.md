# 共享检出被另一条 agent 线切了分支 —— 服务/启动器/画布 全线的静默崩法 (2026-09-26 实测)

## 现象 (三类一起发作, 看起来互不相关)
| 表现 | 真因 |
|---|---|
| 6 个在役服务**重启即挂**: `python3: can't open file '/repo/tools/ss_remote_tap.py': No such file` / `FileNotFoundError` | unit 的 `ExecStart`/`-v` 挂载指向 `/home/ubuntu/lerobot-smolvla-lew`, 该树被切到 `mac-hw` 分支 → main 线的脚本不在那棵树上 |
| 进控制台点「状态空间」→ 弹 **「状态空间模型画布加载失败」** | 画布加载只拼 `<仓库根>/flows/state_space_obs.json`, 而那棵树上没有 `flows/` |
| 控制台"变得很旧"(版本号退回, 缺新节点/新功能) | 那棵树的分支上 `studio.py` 是旧版(665KB/v5.6.0 vs main 808KB/v5.15.8) |
| 点**桌面快捷方式**必踩上面两条 | `XSpace-Studio.desktop` 的 `Exec=` 与 `launch_studio.sh` 里 `GUI_DIR/` 都**硬编码**了那棵共用检出 |

**关键判读**: 老进程已把脚本读进内存, 所以服务"看起来 active"; 只有 restart/重启机器才暴露。多 agent 线共用一个目录时, 这类损坏是**静默**的 —— 不要用 `is-active` 单点判定"链路健康"。

## 修法 (四步, 每步都要复核)
1. **先分清哪棵树是什么**: `git -C <树> branch --show-current` + 比较 `studio.py` 体积/版本号 + `ls <树>/flows`。
   本机约定: `main` 线代码/画布在 **worktree `/home/ubuntu/zmax_rel`**; 共用检出 `/home/ubuntu/lerobot-smolvla-lew` 可能被 APP 线占用。
2. **代码侧多候选定位**(根治"仓库根不对就崩"): 例如画布路径
   ```python
   def _flows_path(name):
       # env > 本检出 > main worktree > 默认检出 > 打包 _MEIPASS; 命中即用, 找不到返回原路径(零回退)
   ```
   取证脚本要**显式模拟**"仓库根=另一棵检出"这一场景(monkeypatch `_repo_root_path`)才算证明修好。
3. **服务侧指向稳定 worktree** + venv 软链(venv 与分支无关):
   ```bash
   ln -s /home/ubuntu/lerobot-smolvla-lew/gui-venv311 /home/ubuntu/zmax_rel/gui-venv311
   sudo sed -i 's#/home/ubuntu/lerobot-smolvla-lew#/home/ubuntu/zmax_rel#g' /etc/systemd/system/<u>.service
   sudo systemctl daemon-reload && sudo systemctl restart <u>   # 逐个 restart 后复核 is-active
   bash scripts/check_unit_paths.sh                              # 扫"引用路径是否还存在"
   ```
4. **启动器去硬编码**: `launch_studio.sh` 用 `GUI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"` 自定位;
   `.desktop`(桌面 + `~/.local/share/applications` 两份都要) 的 `Exec=` 指向稳定 worktree 的启动器。

## 顺带的坑: 两棵树"互补"时不要二选一
共用检出常有 git 之外的大产物(`runs/` `outputs/` `models/*.pt` `data/`), worktree 里没有 →
  *从 worktree 起 GUI 会在别处崩*(实测: `FileNotFoundError: <worktree>/runs/detect/outputs/.../best.pt`)。
做法: 把**缺的运行时产物软链进 worktree**(目录级 `ln -s`, 文件级逐个补链, 幂等), 复核清单:
`flows/<画布>.json` · `runs/**/best.pt` · `models/*.pt` · `outputs/` · `data/`。
这样"main 线代码+画布"与"全部运行时产物"共处一棵树, 不必在两者之间切换。

## 交付口径
报告里写: 根因(哪棵树/哪个分支) · 逐项复核数字(6/6 active · 启动 0 错误 · 进程 cwd) · 一条回滚命令
(`sudo cp <unit>.bak_preworktree <unit>` + `daemon-reload` + `restart`)。

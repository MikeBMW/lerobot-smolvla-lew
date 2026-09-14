# 桌面打包构建 (win .exe / mac .app) 排查 — 2026-09-10 实测
（v5.5.8 构建全挂 → v5.5.9 构建全挂 → v5.5.10 修好。老倪现象："mac 新版报 No module named 'metaworld'"）

## 第一个动作：先分清"依赖没装" vs "构建没产出"
老倪说"新版报 XX 模块缺失"时，**先去 GitHub 看 Build Desktop 的 run 结论**，
再确认 Release 上到底有没有该 tag 的资产。本次真因是 **CI 构建失败 → Release 无资产 →
用户在跑旧包**，跟依赖装没装没关系。

```bash
TOKEN=$(python3 -c "import re;print(re.search(r'https://MikeBMW:([^@]+)@',open('/home/ubuntu/.git-credentials').read()).group(1))")
# 1) 最近 runs 及结论
curl -s -H "Authorization: token $TOKEN" \
  "https://api.github.com/repos/MikeBMW/lerobot-smolvla-lew/actions/runs?per_page=12" \
  | python3 -c "import json,sys;[print(r['id'],r['name'][:40],r['head_branch'],r['conclusion']) for r in json.load(sys.stdin)['workflow_runs'][:12]]"
# 2) run → job → 哪个 step 挂
curl -s -H "Authorization: token $TOKEN" \
  "https://api.github.com/repos/MikeBMW/lerobot-smolvla-lew/actions/runs/<RUN_ID>/jobs" \
  | python3 -c "import json,sys;[print(j['id'],j['name'],j['conclusion'],[ (s['name'],s['conclusion']) for s in j['steps'] if s.get('conclusion') not in ('success','skipped',None)]) for j in json.load(sys.stdin)['jobs']]"
# 3) 拉失败 job 日志
curl -sL -H "Authorization: token $TOKEN" ".../actions/jobs/<JOB_ID>/logs" | grep -iE 'error|Unable to find|Traceback' | tail -12
```
触发构建：tag 推送即触发（`git tag vX.Y.Z && git push origin main vX.Y.Z`）；
手动 `workflow_dispatch` **必须直连 api.github.com**（ghproxy 只代理 GET，POST 会 403 Invalid input），
`curl -X POST -H "Authorization: token $TOKEN" -H "Accept: application/vnd.github.v3+json" \
 https://api.github.com/repos/.../actions/workflows/<file>.yml/dispatches -d '{"ref":"main"}'` → **HTTP 204 = 成功**。

## 三个静默杀手（本次连续踩到）
1. **`--add-data` 指向不存在的目录 → pyinstaller 直接 exit 1**
   原文：`ERROR: Unable to find 'D:\a\...\src\lerobot\skills' when adding binary and data files.`
   我给 `src/lerobot/skills` 加了 add-data，但目录根本不存在（原子技能源码实际在
   `src/lerobot/policies/left_right/state_space/skills`，已被 left_right 整体打包覆盖）。
   **规则：加 add-data 前先 `ls -d` 确认；缺一个目录 = 双平台构建全挂，且报错在最后才出现。**
   同批真实存在的可加：`src/lerobot/memory`（v5.5.1 记忆分层，曾漏打包导致"状态空间画布加载失败"）。
   第三方库（metaworld/mujoco）用 `--collect-all`，不要手拼路径。
2. **懒加载 import 静态分析收不到 → 运行期 No module named**
   引擎里 `import metaworld as _mt` 写在函数内（模块级懒加载单例）→ 必须
   `--hidden-import metaworld --hidden-import mujoco --collect-all metaworld --collect-all mujoco`。
3. **CI 的"验证行"本身会 fail 整个安装步骤**
   `python -c "import metaworld; print(metaworld.__version__)"` —— **metaworld 没有 `__version__`**
   → `AttributeError` → `Install dependencies` FAIL（依赖其实装成功了，metaworld 3.1.1 / mujoco 3.3.0）。
   改成不抛的属性：`hasattr(metaworld, 'ML1')` + `mujoco.__version__`。

## 顺带的版本号纪律
- 发版同步 5 处：`studio.py`(窗口标题 ×3 处 + changelog 注释) / `update_checker.py` /
  `version_sync.py` / `docs_sync.py` / `VERSION.md`。只改 UI 版本不要动历史 changelog 注释。
- 往 VERSION.md 表格插新行要**定位表头行后再插入**；用整行 old_string 做 replace 会把
  新行和下一行拼在一起（本次踩过一次，需用 python 按行插入并检查）。

## 与训练共用的坑（同一批踩到，详见 skill robot-policy-training 的
`references/dagger-residual-vla-closed-loop.md`）
- `cp -r .../checkpoints/last`（symlink）→ 实体目录 → resume 时
  `FileExistsError: '<step>' -> .../last` 崩；用 `cp -rL` 或复制后重建 symlink。
- `train_config.json` 的 `steps` 是**总步数**，续训要写"当前+增量"。
- 续训重写 `config.json` 丢 `type` 键 → `from_pretrained` 报 draccus `Expected a dict with a 'type' key`。
- **杀训练进程别用 `pkill -f lerobot_train`**：命令行自匹配 → 连自己的 shell 一起杀（exit -9，
  后续命令全不执行）。用 `ps -eo pid,args | awk '/lerobot_train/ && !/awk/ {print $1}'` 先列再按 pid 杀
  （同 studio.py 的 `pkill -f "[s]tudio.py"` 一族教训）。
- batch 对速度影响巨大：本机 4060，batch 8 = 4.52 s/step，batch 1 = 1.73 step/s（快 7.9 倍）。
  老倪催"1 小时内训完"时优先降 batch。

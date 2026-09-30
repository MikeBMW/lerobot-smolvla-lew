# 半边失败的 Release 补发 + 失败 run 取证 (2026-09-15 实测)

场景: 用户要「最新版控制台，发布 Windows 和 Mac」。关机时 tag `v5.6.4` 的桌面构建 workflow
是 **Windows job success / macOS job failure**（`Download MLP operation video …` 步骤 41s 就挂），
Release 上只有 `Z-MAX_Console.exe`。本次开机后 3 分钟内闭环：只重跑失败 job → 双包齐。

## 1. 判定口径：资产齐不齐 = Release assets 列表，不是 workflow 颜色

```python
rel = api(f"/repos/{O}/{R}/releases/tags/{TAG}")          # 或 ?per_page=6 一次看多个 tag
print([(a["name"], a["size"], a["updated_at"]) for a in rel["assets"]])
```

- `v5.6.2 / v5.6.3 / v5.6.1 …` 有 `exe + macOS.zip` 两条；`v5.6.4` 只有 exe ⇒ 那一次就是半边成功。
- workflow run 的 `conclusion=failure` **不等于** 什么都没出：一个 run 里多个 job，成功 job 的资产已经上传了。
- 下载可用性最后要落地验证：`curl -sIL "…/releases/download/$TAG/$NAME" | grep -Ei '^HTTP/|content-length'`
  → 必须 `HTTP/2 200` + 真实 content-length。

## 2. 补发：只重跑失败 job（不改代码、不重打 tag）

```bash
curl -s -X POST -H "Authorization: token $TOKEN" -H "Accept: application/vnd.github+json" \
     "https://api.github.com/repos/$O/$R/actions/runs/$RUN_ID/rerun-failed-jobs"     # 201 = 已受理
```

- 成功的 job 不重跑 ⇒ 省时间（本次 macOS 只花 3 分钟，Windows 那 4.7 分钟不重来）。
- **同一个 run id** 上 `conclusion` 变 `success`、`run_attempt` 变 `2`；不要因为 id 没变就以为没重跑。
- 资产步骤用 `svenstaro/upload-release-action@v2` + `overwrite: true` ⇒ 重跑只补缺的资产，已有资产 `updated_at` 不变。
- 重跑前先复查失败步骤依赖的外部 URL：`curl -sI https://datadrive.world/models/xxx.zip`（本次复查是 200，
  847KB 小包，说明原失败是瞬时中断/超时而非资产不存在 ⇒ 直接 rerun 就够，不必改工作流）。
- 重跑后复核两条：`jobs` 里 macOS job `conclusion=success` **且** Release assets 里出现新资产（含 size/updated_at）。

## 3. 失败 run 的取证顺序（由便宜到贵）

```bash
# ① 哪个 job、哪个 step 挂的（1 个请求）
curl -s -H "Authorization: token $TOKEN" ".../actions/runs/$RUN_ID/jobs" | python3 -c "
import sys,json
for j in json.load(sys.stdin)['jobs']:
    print(j['id'], j['name'], j['status'], j['conclusion'])
    for s in j.get('steps',[]):
        if s.get('conclusion') not in ('success','skipped',None): print('   FAIL:', s['name'])"

# ② check annotation = 最短的\"为什么\"（Process completed with exit code 1 / Username and password required）
curl -s -H "Authorization: token $TOKEN" ".../check-runs/$JOB_ID/annotations" | python3 -c "
import sys,json;[print(a.get('path'), a.get('start_line'), (a.get('message') or '')[:200]) for a in json.load(sys.stdin)]"

# ③ 完整日志（要具体文件/hook 时）
URL=$(curl -s -o /dev/null -w '%{redirect_url}' -H "Authorization: token $TOKEN" \
      "https://api.github.com/repos/$O/$R/actions/jobs/$JOB_ID/logs")
curl -s -o job.log "$URL"
```

坑:
- `/actions/jobs/{id}/logs` 用 urllib 直接 GET **403**（它 302 到 `productionresultssa*.blob.core.windows.net`，
  带 Authorization 追跳转会被拒）。正解就是上面 `-w '%{redirect_url}'` 拿地址再匿名下载。
- 下下来的文件**是纯文本日志**（本次 34MB），不要 `zipfile.ZipFile` 打开（`BadZipFile`）。
- 解析时按时间戳前缀切：`l.split('Z ',1)[-1]`；要按 hook 分组（`grep -n 'hook id:'`）再往后读 10 行，
  因为 pre-commit 一次 `--all-files` 会同时挂多个 hook，只看第一处会漏。
- `Node.js 20 is deprecated` 是 warning annotation，别当成失败原因。

## 4. 本次抓到的 CI 症状 → 真因对照

| annotation / 症状 | 真因 | 动作 |
|---|---|---|
| `Username and password required` @ `Log in to Alibaba Cloud ACR` | repo secret `ACR_USERNAME/ACR_PASSWORD` 缺失或过期 | 重配 secret；不是改 workflow |
| 某平台 job 在「下载外部资产」步骤 <1 分钟就挂 | datadrive/ECS/网盘瞬时不可达/限速（两平台并发拉同一包） | `curl -sI` 复查可达 → `rerun-failed-jobs` |
| Quality(pre-commit) 一片红，12 个 hook 同时挂：`end-of-file-fixer` / `trailing-whitespace` / `prettier` / `typos` / `pyupgrade` / `ruff-format(632 文件)` / `mypy` 的报错路径都指向 `docs/skills/**`、`docs/memory/**` | **把上千文件的技能/记忆镜像 commit 进带 pre-commit 的仓库** —— 镜像 md/tex/py 天生不过 lint（mypy 还因同名 `_hermes_home.py` 直接 Duplicate module） | 给镜像目录加全局 `exclude`（或 CI 只查 `src/ tools/ docker/`）；镜像内容不做格式化 |
| 同一片红里零星几处真代码问题 | `experiments/train/trace_train.py:179,233 breakpoint()`、`train_smolvla_mini.py:38 pdb`、`config/state_machines/motion/*.yaml:23` YAML 语法、`tools/*.py` typos(`lew`) | 删调试断点 / 修 YAML 引号 / typos 白名单；这些才是需要人工改的 |

教训: 镜像类大目录一入库就会把 Quality 变成长红；「CI 变红」要第一时间分「镜像噪音 vs 真代码」两类，
否则会去修 632 个只读镜像文件的格式（纯浪费）。

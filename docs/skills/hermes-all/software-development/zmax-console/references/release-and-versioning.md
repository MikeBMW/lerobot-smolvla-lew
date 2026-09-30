# Z-MAX Console — 发版 / 版本号 / CI 取证 (2026-09-22 实证)

老倪常说的「小版本迭代, 发布 windows 和 mac 版本」= **改齐版本号 → 提交 → 打 tag → 推 tag**。
真源: `VERSION.md`(版本管理规范) + `.github/workflows/build-win-exe.yml`(双平台构建)。

## ⚠️ 最容易踩的坑: 只提交、不打 tag ⇒ CI 永远不构建

实测(v5.11.4 发版时发现): `release v5.11.2` / `v5.11.3` 两个提交都在仓库里,
但 **`git tag -l 'v5.11*'` 只有 v5.11.1** —— 两次迭代从未打 tag, 所以
「Build Desktop (Windows .exe + macOS .app)」**一次都没跑过**, 用户以为发了版其实没有包。

判据(发版前先查):
```bash
cd ~/lerobot-smolvla-lew
git tag -l 'v5.11*'                     # 本地 tag
git ls-remote --tags origin | tail -5   # 远端 tag (真触发 CI 的是这个)
git log --oneline -8 --grep="release v5" # 有提交 ≠ 有 tag
```

## 发版步骤 (小版本 = 补丁位 +1; 功能模块 = 次版本 +1)

版本号 **5 处必同步**(VERSION.md 规定, 少一处就出现"界面 5.11.3 / 更新检查 5.11.2"这种不一致):
```
1. tools/gui/studio.py         ver = QLabel("Z-MAX vX.Y.Z") + setWindowTitle(... vX.Y.Z ...) ×2
                               + __init__ 里 changelog 注释按 `vX.Y.Z: 变更点1+变更点2` 追加到最前
2. tools/gui/update_checker.py CURRENT_VERSION = "vX.Y.Z"
3. tools/gui/version_sync.py   zmax_ver = "X.Y.Z"
4. tools/gui/docs_sync.py      "version" 与 "zmax_version" 两键
5. VERSION.md                  版本历史表首行追加
```
然后:
```bash
git add -A && git commit -m "release vX.Y.Z: ..." && git push origin main
git tag -a vX.Y.Z -m "Z-MAX vX.Y.Z: ..." && git push origin vX.Y.Z   # ← 这一步才触发构建
```
写 tag 时若上一版曾"只提交未打 tag", 在变更摘要里点明"本次一并补齐" (否则以后翻历史会误判成漏发)。

## CI 状态怎么查 (本机 **没有 gh**)

用 GitHub API + 仓库凭据(在 `~/.git-credentials`, `store` helper; token 40 位, 别打印内容):
```python
import json, re, urllib.request
tok = re.search(r"://([^:]+):([^@]+)@", open("/home/ubuntu/.git-credentials").read()).group(2)
def api(p):
    r = urllib.request.Request("https://api.github.com"+p,
        headers={"Authorization": f"token {tok}", "Accept": "application/vnd.github+json"})
    return json.load(urllib.request.urlopen(r, timeout=30))
for r in api("/repos/MikeBMW/lerobot-smolvla-lew/actions/runs?per_page=5")["workflow_runs"]:
    print(r["created_at"], r["name"], r["status"], r.get("conclusion"), r["head_branch"])
```
- 挂一个后台监视直到结束(轮询 `actions/runs/<id>`, 再查 `.../runs/<id>/jobs` 看每个 job 结论,
  最后查 `/releases/tags/<tag>` 列产物大小) —— 脚本: `~/.hermes/scripts/watch_release_build.py <tag>`
- 一次 tag 会同时触发: **Desktop(Win .exe + macOS .app)** · Simulink 模型验证 CI · Docker 镜像构建;
  `Create Release and Publish to PyPI` 是上游 HF 专属 job, `skipped` 属正常, 不是失败。

## 打包版行为差异要记住 (历史踩坑)

- 打包版**只有内置素材**, 拉外部演示视频失败不该卡整次发版(`::warning::` + 占位放行);
  mac job 曾因 `ls | head` 遇 `pipefail` 报 Broken pipe 而全挂 → 那条要 `|| true`。
- Windows/macOS 版不读 `~/lerobot-smolvla-lew/...` 硬编码路径(打包后 `_MEIPASS`), 场景/权重都要随包。
- 发版后要真跑一次自证(`--engine-selftest` 在打包产物内 import mujoco/metaworld 并步进),
  只查"文件在不在包里"不够。

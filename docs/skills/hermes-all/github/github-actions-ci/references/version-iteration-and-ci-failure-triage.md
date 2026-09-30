# 中版本迭代 → 双平台发布 & CI 失败归属判定（2026-09-25 v5.15.0 发版实测）

> 与 `references/pre-tag-version-sync-ghless-poll.md` 同读：那篇讲「**忘了同步**版本号」，
> 本篇讲「**同步时改错**」+「怎么判某个 CI 失败是不是自己造成的」。

---

## 1. 版本串只改"显示形态" —— 别全量替换（会篡改发版历史）

```
实测: grep -c 'v5.14.0' tools/gui/studio.py   →  **5 处**
      其中只有 3 处是界面显示（菜单栏 QLabel / 两处 setWindowTitle）
      另外 2 处在**历史变更块**里（块标题 `# v5.14.0:` 及其正文）
```

🔴 **事故（被自建守卫拦下，文件未被改动）**：
把 `v5.14.0 → v5.15.0` **全量替换**，会把**历史变更块标题 `# v5.14.0:` 一起改名**
= **篡改发版历史**。那一次守卫在**写盘前**中止，文件完好。

**正确做法**：
```python
OLD, NEW = "Z-MAX v5.14.0", "Z-MAX v5.15.0"     # ★ 精确到显示形态, 不碰 "# v5.14.0:"
src2 = src.replace(OLD, NEW)
anchor = "# v5.14.0:"                            # 历史块用**独立锚点**定位
src2 = src2.replace(anchor, ENTRY + anchor, 1)   # 只在它**前面插入**新块（时间倒序）
```

**升级脚本必须自带断言**（写完即验，不靠肉眼；任一条不过就中止且不落盘）：
```
□ 替换处数 == 预期数            # 少于预期 → 中止, 不要猜
□ 旧显示串残留 == 0
□ 历史块标题 `# <旧版本>:` 仍在          ← 这条专防"篡改历史"
□ 新变更块已插入且位于旧块之前（时间倒序）
□ ast.parse 通过（被改的是 .py 时）
```

改前先 `cp studio.py /tmp/studio_<旧版本>_backup.py` → 失败秒回滚。

**顺序**：版本同步 commit → push main → `git tag -a vX.Y.0` → push tag → CI 双平台构建 → 验资产。

**中/小版本口径**（本仓库）：应用发布系列走 `v5.MAJOR.MINOR`（如 v5.14.0 → **v5.15.0** = 中版本）；
`pyproject.toml` 的 `0.5.2` 是**库版本**，与 tag 不是同一条线 —— 不必强行对齐（PyPI release
job 因版本不匹配显示 `skipped` 属**正常**，不是失败）。

---

## 2. 判"这个 CI 失败是不是我造成的" —— 查该 workflow 的历史

本轮 tag 触发的 `docker-console.yml` 失败在 `Log in to Alibaba Cloud ACR`。
**不要急着修**，先列该 workflow 最近几次 run：

```
GET /repos/{O}/{R}/actions/workflows/<file>.yml/runs?per_page=8
# 实测: v5.11.1 / v5.11.4 / v5.11.5 / v5.12.0 / v5.12.1 / v5.13.0 / v5.14.0 / v5.15.0 **全部 failure**
```

⇒ **每个历史 tag 都失败 = 既有环境问题**（此处 = ACR 凭据过期），**不是本次改动引入的**
  → 不追、不顺手改；如实报"既有问题"并等用户定（用户原话：**"不用管ACR"**）。
  反之，以往都绿、这次才红 → 才是本次改动的问题。

**一个 tag 常并发触发多个 workflow，先分类再下结论**（本轮同时 5 个）：
`in_progress` 在跑 · `success` 过 · `failure` 且历史全红 = 既有 · `skipped` 被条件跳过。
只看到"有 failure"就当成自己的回归 = 误判。

**定位到具体失败步骤**（比只看 workflow 结论省事）：
```
GET .../actions/runs/<RUN_ID>/jobs   → 找 conclusion==failure 的 job
                                      → 再取其 steps 里 conclusion==failure 的 name
```
本轮由此一步定位到 `Log in to Alibaba Cloud ACR`（凭据问题，非代码问题）。

---

## 3. 发布完成的判据（不能只看"构建绿"）

```
① 工作流: name == "Build Desktop (Windows .exe + macOS .app)" 且 completed/success
   （该 workflow 一次 tag 并行构建 Windows 与 macOS，各自挂到**同一个** Release）
② 资产列表: GET /repos/{O}/{R}/releases/tags/<tag>
   → 每个平台都有产物且 size 合理（实测 .exe 156.8MB / macOS.zip 122.8MB）
③ 下载可达: 对 browser_download_url 做 curl -sIL → HTTP 200
   （发布页 + 每个资产都验；注意必须 -L，302 到对象存储）
```

资产 sha256 / 302 / assets-API 带 token 400 等下载坑见 SKILL.md「下载路径坑」
与 `scripts/verify_release_assets.sh`。

---

## 4. 诚实汇报纪律（发版也不例外）

```
□ 区分"我造成的" vs "既有的"：给证据（该 workflow 历次 run 的结论列表），不要含糊
□ 未达成的项直说（例：某平台的验证步骤被 skip → 明说 skip，不说"全部通过"）
□ 用户明确放掉的项（"不用管ACR"）→ 后续汇报里一句话带过，不再反复提
□ 中间的自我纠错要留痕：本轮"版本脚本差点改历史 → 守卫拦下 → 改用精确匹配 → 断言全过"
   写进变更块, 比只报"发布成功"有用
```

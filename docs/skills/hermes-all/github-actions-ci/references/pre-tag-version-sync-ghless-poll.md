# 发版前置核对 + gh-less CI 轮询 (2026-09-08 v5.3.0 发布实测)

Z-MAX Console 桌面版发布全流程的"发布侧"经验 (仓库侧版本同步见
zmax-console references/version-bump-checklist.md + release-run-v530-2026-09-08.md)。

## ⚠️ 事故: v5.2.0 tag 与 app 内版本文件脱节
tag v5.2.0 已发布, 但该 tag 指向的提交里 `tools/gui/update_checker.py CURRENT_VERSION` /
`studio.py` 标签仍 v5.1.0 → 用户 exe 内"检查更新"永远提示升级到旧版。
成因: 功能代码由并行分身/跨会话 `git add -A` 提交并发布, 版本同步 commit 没做/没推。
本地 main 超前 origin 十几个提交但 grep 版本号仍旧值 = 典型症状。

## 铁律: 发新 tag 前核对上一个 tag 的文件内容
```bash
git show v5.2.0:tools/gui/update_checker.py | grep CURRENT_VERSION   # 必须 == v5.2.0
git show v5.2.0:tools/gui/studio.py | grep -m1 'QLabel("Z-MAX'          # 同上
```
漏了 → 在 main 补"版本号同步" commit 后再发新 tag。顺序: 版本同步 commit → push main →
tag → push tag → CI → 验证。旧 tag 资产已错不用回改, 由新 tag 纠正。

## tag 推送后无 gh CLI: curl API 定位/轮询 run
```bash
TOKEN=$(sed 's|https://[^:]*:\(.*\)@github.com|\1|' ~/.git-credentials)   # token 提取
curl -s -H "Authorization: token $TOKEN" \
  "https://api.github.com/repos/O/R/actions/runs?event=push&per_page=8"   # 认 run id + name
curl -s -H "Authorization: token $TOKEN" ".../actions/runs/$RUN_ID"        # status/conclusion
curl -s -H "Authorization: token $TOKEN" ".../actions/runs/$RUN_ID/jobs"   # 每 job 结论
```
- tag 推送并行触发多个 workflow (build-win-exe / docker-console / simulink-ci / pypi release)。
  认准 name="Build Desktop (Windows .exe + macOS .app)"; Docker 失败历史惯例不影响 exe 发布;
  PyPI release 无配置时显示 skipped 属正常。
- 长构建 (~10-20min): 落盘轮询脚本 (curl+sleep 循环, `completed*` break → 再拉 jobs + 
  `releases/tags/<tag>` 资产摘要含 size+digest) + terminal background=true notify_on_complete=true,
  完成通知回来再验证资产, 别前台干等。
- release 由 workflow 里 svenstaro/upload-release-action 自动建 (overwrite=true), 无需手动建。
- 资产 sha256 验证 + 下载路径坑 (302 必须 -L / digest 去 `sha256:` 前缀 / assets API 带 token
  可能 400) 见 SKILL.md「下载路径坑」+ scripts/verify_release_assets.sh。

## 飞书通知两时机
tag 推送后发"发布启动"; CI completed + 资产验证通过后发下载链接 (含大小)。
模板: zmax-console templates/send_feishu_text.py (纯文本, code=0 success 即成功)。

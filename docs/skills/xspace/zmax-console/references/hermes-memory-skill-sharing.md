# 记忆 + 技能共享到仓库 / 凭据脱敏 / 关机前收尾 (2026-09-15 实测)

> 老倪口径: 「共享你的所有记忆到 github 或 ECS」·「保存数据，小版本迭代，准备关机」。
> 每次验收后走一遍: 数据 → 版本 → 推送 → 共享记忆/技能 → 通知飞书 → 收尾。

## 一、共享通道 (两条, 都要走)

1. **既有 cron 通道** `tools/sync_hermes_to_repo.sh` (cron `hermes-skill-memory-sync` 每 6h):
   - zmax-console 全家 → `docs/skills/xspace/zmax-console/` (SKILL.md + references + scripts + templates)
   - 24 个关键 mlops/github/devops 技能 → `docs/skills/xspace/<name>`
   - **MEMORY.md + USER.md** → `docs/memory/hermes-jingjing-{memory,user}-<日期>.md` + `-latest.md`
   - `docs/skills/manifest.json` (技能数/最后同步, 天级幂等不刷屏)
   - 手工跑用 `bash tools/sync_hermes_to_repo.sh --no-push` 然后自己用下面 §三 的推送法
     (脚本内 `git push origin` **不带**认证头 → 本机 .git-credentials 的 host 是 github.com 而
     代理 URL host 是 ghproxy.net → 会卡在等密码, 所以推送统一走 §三)

2. **"所有技能"全量镜像** (老倪说"所有"时用; 只有 SKILL.md + references/scripts/templates 的文本, 很小):
   - 目标 `docs/skills/hermes-all/<技能名>/` + 可读索引 `docs/skills/hermes-all-index.md`
     (技能名/分类/文件数/说明 ← 从 frontmatter 的 description/title 抽)
   - 实测规模: **155 个技能 / 1115 文件 / 13MB** (源 `~/.hermes/skills` 看似 50MB, 大半是
     `.curator_backups/*.tar.gz` 本机快照 → **必须排除**)
   - 排除规则: `.curator_backups/` · `__pycache__/` · `.git/` · 单文件 >2MB (Git 精简纪律); 本次实际跳过 **0 个**
   - 同名技能 (不同分类) → 用 `<分类>--<名>` 去重

## 二、⚠️ 推送前必做: 凭据扫描 + 脱敏 (本次被 GitHub 拦下才发现的)

**症状**: push 被拒 —— `remote: error: GH013: Repository rule violations found for refs/heads/main`
→ `GITHUB PUSH PROTECTION — Push cannot contain secrets`, 并列出 `commit / path:行号`
(本次是 `hermes-crash-recovery/references/2026-07-28-session.md:31` 与
`multi-agent-project-recovery/references/zmax-recovery-transcript.md:79` 各一处**真实 GitHub Token**)。

**处置纪律 (顺序不能变)**:
1. **绝不点** GitHub 给的 `unblock-secret` 链接 ("allow secret") —— 那是把凭据公开到远端。
2. 先扫全量: `scripts/scan_redact_secrets.py` (无参只扫, 打印**文件:行 + 类型 + 长度**, 不打印值)。
   覆盖面: `~/.hermes/skills` · 仓库 `docs/skills` · `docs/memory` · `backups`。
3. **源文件与镜像一起脱敏** (只改镜像 → 下次 cron 同步又把密钥带回来)。
   `scripts/scan_redact_secrets.py --apply` → 替换成 `[REDACTED:<类型>]`。
4. **改写本地未推提交** (`git add ... && git commit --amend`) → 让远端历史里**从不出现**该密钥;
   若已推过则需评估轮换凭据 (注意 amend 只对未推提交有效)。
5. 复扫应 0 命中; 再用 `git grep -lE 'gh[pousr]_[A-Za-z0-9]{20,}' <每个相关commit> -- docs/` 逐个提交
   证明"从未进远端" (本次 5 个相关提交全 0 命中)。
6. 汇报里点明: 该凭据曾以明文存在于本机文件 → 建议轮换一次; 并把"凭据一律 [REDACTED] 落盘"写进记忆。

扫描模式 (2026-09-15): `gh[pousr]_[A-Za-z0-9]{20,}` · `github_pat_[A-Za-z0-9_]{20,}` ·
`sk-[A-Za-z0-9]{20,}` · `AKIA[0-9A-Z]{16}` · `xox[baprs]-...` · `AIza[0-9A-Za-z_\-]{30,}`。
⚠️ 技能 references 里最容易藏凭据 (历史会话记录、排障转写、`.env` 片段), **镜像技能前必扫**。

## 三、推送法 (ghproxy + 显式认证头, 只能靠 ls-remote 判成功)

```bash
CRED=$(python3 -c "import re;print(re.search(r'https://([^/\s]+)@github\.com', open('$HOME/.git-credentials').read()).group(1))")
AUTH="Basic $(printf '%s' "$CRED" | base64 -w0)"
M="https://ghproxy.net/https://github.com/MikeBMW/lerobot-smolvla-lew.git"
git -c http.sslVerify=false -c http.version=HTTP/1.1 -c http.postBuffer=524288000 \
    -c http.extraHeader="Authorization: $AUTH" push "$M" HEAD:refs/heads/main
git -c http.sslVerify=false ls-remote "$M" refs/heads/main    # 远端 SHA == 本地 HEAD 才算成
```
- tag 同理: `push "$M" refs/tags/vX.Y.Z`。
- **别用 `| tail` 看结果** (管道退出码是 tail 的 0, 假成功)。
- 内容可达性抽查: `raw.githubusercontent.com` 在本机常 **HTTP 000** (抖动, 不代表没推上去) →
  用 `https://ghproxy.net/https://raw.githubusercontent.com/<repo>/main/<path>` 复核 (200 = 已共享)。

## 四、通知飞书 (含 @所有人 + 视频)

- 凭据: `~/.hermes/.env` 里**只有** `FEISHU_APP_SECRET`, **没有** `FEISHU_APP_ID` 也没有 chat id →
  app_id 兜底 `cli_a87851ffe46b500d`; chat id 兜底两个已知群:
  dataworld `oc_c0b4048546145c5c581ddd1a9e8f565d` · 静界群 `oc_74ef27c7c49782b7ffbf0543cf8a2d75`
  (两个群都发; 老倪说"所有人"= 每个群都 `@所有人`)。
- 取 token: `POST open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal` {app_id, app_secret}
- @所有人: `msg_type=text` + `content={"text": '<at user_id="all">所有人</at>\n…'}` (`ensure_ascii=False`)
- 发视频: 先 `POST /im/v1/files` multipart (`file_type=mp4`) → `file_key` → `msg_type=media` 发文件,
  再补一条 text 说明 (模板 `templates/send_feishu.py`); 成功判据 `code==0` + 记 `message_id`。
- ECS 上传通道本机**无凭据** (sshpass 装了但无 39.102.211.79 的密码/密钥) → 走 GitHub + 飞书发文件。

## 五、关机前收尾清单 (老倪「准备关机」)

1. **保存数据**: 引擎运行时产物 (`reports/intact_goal_frame_optical.npy` / `intact_l3_cond.json`)
   刷新入库 · `backups/mem_<日期>.md` 记忆备份更新到当前版本 · 工作区 0 未提交。
2. **小版本迭代**: 五处版本号 + changelog 摘要 + `VERSION.md` 历史行 + tag + push
   (补丁=修复/小优化; 见 `references/version-bump-checklist.md`)。
3. **停非服务型守护**: `pkill -f "[a]uto_loop.py"` (等小芳数据的中转守护, 不写盘中断风险);
   重启命令留给用户: `cd ~/lerobot-smolvla-lew && ~/lerobot-venv/bin/python tools/auto_loop.py >> outputs/auto_loop.log 2>&1`
4. **确认哪些会自动恢复**: `hermes-gateway.service` (systemd, active) = **cron 调度器就住在 gateway 里**
   (`hermes cron status` 显示 "Gateway is running — cron jobs will fire automatically" + ticker heartbeat)
   → 开机自动续跑; `zmax-data-mount.service` (E盘数据盘 bind 挂载, oneshot)。
5. **报告里给开机三步**: ①先 `date` 对时间 (本机曾开机 NTP 拨钟偏 7.5h) ②`hermes cron status` +
   `hermes cron list | grep next_run` 确认 next_run 都在未来 (跳变后停在过去的用 `hermes cron edit` 触发重算)
   ③需要时重启 auto_loop; 飞书 99991663 → `sudo systemctl restart hermes-gateway.service`。
6. 收尾自检: GPU 空闲 (`nvidia-smi`) · 磁盘红线 (`df -BG /` ≤300G) · 无残留进程
   (`pgrep -af` 时**别用会匹配到自己的模式** —— 用 `[a]uto_loop` 方括号技巧)。

## 六、陷阱速记

- `git status` 里 62 个未跟踪文件多半是证据/视频/npz → `.gitignore` 已挡 `reports/*.mp4|png|pdf|npz|xlsx`、
  `checkpoints/`、`*.bak-*`; **别用 `git add -A`** 提交共享内容 (会带进 2000+ 文件), 显式列清单。
- 画布 JSON 有备份时 (`flows/*.bak-*`) 记得 gitignore, 否则每次 `git add flows/` 都会带上。
- 记忆有字符上限 (2200) → 新增教训要**同批**删/压缩旧条目 (一次 batch 调用), 否则被拒。

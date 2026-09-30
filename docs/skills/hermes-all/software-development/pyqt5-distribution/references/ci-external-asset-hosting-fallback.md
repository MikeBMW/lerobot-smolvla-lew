# CI 取不到外部权重/资产时的兜底: 改用 GitHub Release 资产 (2026-09-19 实测)

## 症状
Windows job 在 **"Download … weights" 步骤** fail, 后面所有步骤 skip;
mac job 同样会挂。日志里就是 `curl -fsSL` 非零退出 (404/连接失败)。

## 诊断顺序 (5 分钟定位)
1. **看是哪一步失败**: `GET /actions/runs/{id}/jobs` → 逐 step 的 conclusion (别下载整个 log)。
2. **本地核对文件与校验**: `ls -l` + `md5sum` 目标文件 → 与 workflow 里 assert 的 MD5 对比。
   本例: 本地文件与 MD5 **完全正确** ⇒ 源站问题, 不是构建问题。
3. **从本机测源站**: `curl -sI <url>`。本例返回**空** ⇒ 本机根本连不上域名 ✗
   → 注意区分"本机连不上"与"源站真缺文件": 同一 workflow 里**别的**下载步骤(如视频包)成功了
   ⇒ 域名在 GitHub runner 侧可达, 只是**那几个文件不在**(404) ✓ 结论精确。

## 兜底修法 (不依赖对象存储/ECS, 不违反"权重不进代码库")
把权重挂到 **GitHub Release 资产**, 让 CI 从 GitHub 自己拉:
1. 建/找一个 release 专门托管资产 (轻量 tag, 如 `weights-v1`):
   `POST /repos/{o}/{r}/releases {"tag_name":"weights-v1","name":"模型权重托管 (CI 用)"}`
2. 上传 (注意**上传域名是 `uploads.github.com`**, 不是 api.github.com):
   `POST https://uploads.github.com/repos/{o}/{r}/releases/{id}/assets?name=<file>`
   headers: `Authorization: token <TOKEN>` · `Content-Type: application/octet-stream`, body = 文件字节
   返回体里的 `browser_download_url` 就是可直接 `curl -fsSL` 的公开 URL ✓
3. workflow 里把 URL 换成该 `browser_download_url`**同时保留 MD5 assert** (防串版本/截断);
   两个 job (windows + macos) 的 URL 都要改 (sed 全局替换后 `grep -n` 复核两处都在)。
4. **重新触发同一 tag 的构建**, 不要改 tag 号 / 不要 force-push tag:
   `POST /actions/workflows/<wf>.yml/dispatches {"ref":"main","inputs":{"tag":"vX.Y.Z"}}`
   (upload-release-action 的 `overwrite: true` 会替换旧资产)
5. 轮询 `GET /actions/workflows/<wf>.yml/runs?per_page=3` → 看 `status` + 各 job 的 conclusion,
   完成后 `GET /releases/tags/vX.Y.Z` 取 `assets[].browser_download_url` **再发链接**。

## 要点
- 资产 URL 走 github.com (CI 侧天然可达), 避开国内对象存储/域名可达性问题。
- 权重仍**不在代码库** (Release 资产) ⇒ 同时满足"大文件不进代码库"与"CI 可复现取数"。
- token 来源: `~/.git-credentials` 里 `https://user:TOKEN@github.com` → **只取冒号后、@ 前**那段
  (把 user 拼进 token 会 401)。
- 复核清单: 两个 job 都 success ✓ · Release 有全部资产(browser_download_url) ✓ · 说明里写明
  macOS 未签名需"右键→打开" ✓

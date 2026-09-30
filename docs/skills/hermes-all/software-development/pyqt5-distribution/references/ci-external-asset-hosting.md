# CI 外部资产取数失败 — 定位与修复 (2026-09-19 实测)

场景: tag 触发的双平台 Release 构建中，某个 job 在「Download <权重/资产>」步骤 fail，**其余步骤全绿**。

## 根因判定

该步骤形如 `curl -fsSL https://<静态站>/models/<权重>.pt`（`-f` ⇒ 4xx 立即失败）。
静态站本身可达（**同目录其他文件——如视频包——的下载步骤成功**）⇒ 不是网络问题，
是**托管侧那几个文件缺失/404**。

## 5 分钟定位顺序

1. `GET /repos/{o}/{r}/actions/runs/{run_id}/jobs` → 打印每个 step 的 `conclusion`，锁定 failure 的步骤名。
   （比抓整段日志快得多。**job logs API 会 302 到签名 URL，带 Authorization 头跟过去会 403**
   `Server failed to authenticate the request…` —— 不要在日志抓取上耗时间。）
2. 打开该 workflow，看那一步的 URL 以及它附带的 `md5` 断言。
3. 本地 `md5sum models/<file>` 与 workflow 里的期望值比对 → **相等 ⇒ 本地文件没问题，问题在托管侧**。
4. 本机 curl 该 URL：无响应/404 ⇒ 确认缺失。
   注意：**本机可能整域不可达**（国内网络/防火墙），不能据此推断 CI 也取不到；
   判据是「同一目录其他文件的步骤是否成功」。

## 修法：改用 GitHub Release 资产托管（无需静态站/ECS 的 SSH 权限）

同时满足「权重/大文件不进代码库」的规约：资产挂在 Release 上，不进 git 历史。

```
1) 建专用 Release 作资产仓库
   POST /repos/{o}/{r}/releases   {"tag_name":"weights-v1","name":"模型权重托管 (CI 用)"}

2) 上传（域名是 uploads.github.com；body = 文件二进制；Content-Type: application/octet-stream）
   POST https://uploads.github.com/repos/{o}/{r}/releases/{id}/assets?name=<file>
   → 得到 https://github.com/{o}/{r}/releases/download/weights-v1/<file>

3) 改 workflow：**win 与 mac 两个 job 的 curl URL 都要改**，保留原 md5 断言

4) 同 tag 重跑（不必新 tag）：
   POST /repos/{o}/{r}/actions/workflows/<wf>.yml/dispatches
        {"ref":"main","inputs":{"tag":"vX.Y.Z"}}

5) 轮询：GET /actions/workflows/<wf>/runs?per_page=3  →  GET /actions/runs/{id}/jobs
   （看每个 job 的 status/conclusion；Windows job 约 3~5 分钟，mac 约 8~15 分钟）
```

要点：资产 URL 在 GitHub runner 侧**必然可达**；本机能否访问静态站与方案无关。

## 相关背景（本仓库既有做法）

历史上权重/视频走 ECS 静态目录 `root@39.102.211.79:/www/wwwroot/datadrive.world/models/`（chmod 644），
CI 里 `curl -fsSL -o ...` 再 `--add-data` 进包。该通道依赖外部机器可达性 —— 一旦本机连不上 ECS
（22 端口超时）或域名不可达，就**无法从本机补文件**，此时切 Release 资产是最快的自救路径。

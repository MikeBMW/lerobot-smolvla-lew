# CI 下载"权重/大资产"步骤失败 = 自建静态托管 404 (2026-09-19 发 v5.10.0 实测)

## 症状
Windows job 挂在「下载流形/yaw 试抓头权重」步(下载失败/404)，但**同一域名下的其它文件(视频包)那一步是成功的**。
⇒ 不是域名/网络问题，是**那几个文件在静态主机上没有** ✗。(本地仓库里的文件 md5 与 workflow 期望值一致 ✓)

## 诊断顺序 (别猜)
1. **先取失败步骤名**: `GET /repos/{O}/{R}/actions/runs/{id}/jobs` → 逐 step 看 `name` / `conclusion`。
   一眼定位到步，比翻整段日志快。
2. **同 host 对照**: 同域的另一个资产 URL 通、目标 URL 404 ⇒ 文件缺失，不是 host 挂。
3. **本地核 md5**: 与 workflow 里写死的期望 md5 比对。一致 ⇒ 文件没问题，只是没被托管上去。
4. 沙箱里直接 `curl -sI <url>` 判有无；注意**开发机可能访问不到那个自建域名**，
   这时以 CI/Runner 视角为准(同 run 里另有同域成功的步骤就是证据)。

## 修法 (遵守"权重/大文件不进代码库")
用 **GitHub Release 资产**当分发源：

```bash
# 1) 建一个专门当"资产库"的 release —— tag 与发版 tag 分开(如 weights-v1)，以后只往上加文件
POST /repos/{O}/{R}/releases          {"tag_name":"weights-v1","name":"weights-v1"}

# 2) 上传: 端点是 uploads.github.com (不是 api.github.com)，body 是二进制文件字节
POST https://uploads.github.com/repos/{O}/{R}/releases/{release_id}/assets?name=<file>
```

3) 把 workflow 里的下载 URL 改成
   `https://github.com/{O}/{R}/releases/download/weights-v1/<file>`
   —— **保留原有的 md5 校验步** ✓ (换托管源不能让校验失效)。
4) 用 **workflow_dispatch 重跑** (带 tag 输入) —— **不必移动/重建 tag**；本次双平台 job 一次全绿 ✓。

## 通用规则
CI 依赖的大文件(模型权重/数据包)**要么放 Release 资产、要么放稳定 CDN**。
放在自建静态主机上的文件会被人挪走/删掉，而 CI 只会在**发版那一刻**才发现 ✗ ——
所以"发版前先跑一次 dry-run 或先 probe 所有下载 URL"比事后救火便宜。

# Z-MAX 中版本迭代 / Release 流程 (2026-08-02 实测两次: v1.1.0, v1.2.0)

老倪"更新，推代码，中版本迭代" = 中版本号 +1 (v1.1.0 → v1.2.0)。完整流程:

## 1. 版本号更新 (GUI 控制台)
`tools/gui/studio.py` 里 `setWindowTitle(f"XSpace Studio — Z-MAX v<X>.0-<tag> · {self._git_short()}")` 更新版本串 + 注释说明本版特性。

## 2. 生成中版本报告
`tools/gen_report_v120.py` 模式 (每版一个): 9 项新功能表 + 模型迭代对比表 (MSE/提升%) + 数据链路表 (训练队列/快照归档/实时帧/本地训练路径) + commit SHA。输出 `docs/CICD_REPORT_v<X>.html` (~3KB)。

## 3. commit + tag + push
```bash
git add -A && git commit -m "release: Z-MAX v<X> — <特性摘要>"
git tag -a v<X> -m "Z-MAX v<X>: <摘要>"
timeout 120 git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=10 push origin main --tags
```
注意: 历史 tag (v1.0.5 等) 已存在, `push --tags` 报 `! [rejected] ... (already exists)` 是**正常的**, 只确认新 tag 推上去即可 (`git ls-remote origin v<X>`)。

## 4. GitHub Release (gh CLI 未装 → 用 REST API)
```python
# /tmp/create_release_v<X>.py 模式
cred = open("~/.git-credentials").read()
token = re.search(r"https://([^:]+):([^@]+)@github.com", cred).group(2)
requests.post("https://api.github.com/repos/MikeBMW/lerobot-smolvla-lew/releases",
  headers={"Authorization": f"token {token}"},
  json={"tag_name": "v<X>", "name": "...", "body": markdown, "draft": False, "prerelease": False})
```

## 5. 附件上传 (报告 HTML)
```bash
RELEASE_ID=$(curl -s -H "Authorization: token $TOKEN" \
  https://api.github.com/repos/MikeBMW/lerobot-smolvla-lew/releases/tags/v<X> | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
curl -s -X POST -H "Authorization: token $TOKEN" -H "Content-Type: text/html" \
  --data-binary @docs/CICD_REPORT_v<X>.html \
  "https://uploads.github.com/repos/MikeBMW/lerobot-smolvla-lew/releases/$RELEASE_ID/assets?name=CICD_REPORT_v<X>.html"
```
验证: 返回 JSON 含 `name` + `size`。

## 交付汇报模板
向老倪汇报: Release URL + tag SHA + 附件 + 新功能表 (9项) + 模型迭代数字 (MSE 提升%) + 全链路状态 (视频流/监控/模型/队列)。

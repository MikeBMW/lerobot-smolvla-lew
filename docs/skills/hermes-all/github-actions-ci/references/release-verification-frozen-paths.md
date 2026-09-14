# Release 资产验证 & PyInstaller frozen 路径 (2026-08-26 v3.2.1 发版实战)

本文件记录 v3.2.1 发版验证踩坑全过程。SKILL.md 正文的 inline 段落（后台 curator 的
read-before-write 门禁 + dedup 阻止了正文 patch）等价内容如下，可直接抄进正文对应小节；
`scripts/verify_release_assets.sh` 是可直接复用的完整脚本。

## 1. GitHub 资产下载: API 端点被 WAF 拒 → browser_download_url

**症状链（实测）**:
- `api.github.com/repos/O/R/releases/assets/{id}` + `Authorization: token` +
  `Accept: application/octet-stream` → HTTP 400 "Whoa there! ... invalid request"（GitHub WAF）
- curl 默认 HTTP/2 下更早失败: `curl: (43) Failed sending HTTP request`
- `--http1.1` 能收到响应但仍是 400
- python urllib 同样被拒（403 on redirect，见下）

**根因**:
- api.github.com 的资产下载端点在本网络环境下对带 token 的请求直接 WAF 拦截
- 302 重定向到 signed URL（Azure release-assets.githubusercontent.com）后，
  **urllib 会把 Authorization header 原样带到签名 URL → 403 "Server failed to authenticate"**；
  curl -L 跨域默认剥离 Authorization，所以 curl 反而更安全
- signed URL 对多余 header 敏感：带 `Accept-Encoding: gzip, br, zstd` 之类的也可能 400

**可行方法（2026-08-26 验证通过）**:
```bash
# digest 从 API 元数据拿（releases/tags 端点不被 WAF 拦）
TOKEN=$(grep -oP 'https://[^:]+:\K[^@]+' ~/.git-credentials | head -1)   # ⚠️ head -1 必须:
# .git-credentials 有多行重复 token，grep -oP 全取 → header 值含换行 → urllib ValueError
curl -sL -H "Authorization: token $TOKEN" \
  "https://api.github.com/repos/O/R/releases/tags/v3.2.1"   # assets[].digest = sha256
# 下载走 browser_download_url，无需 token，302 后自动换 signed URL
curl -sL -C - -o Z-MAX_Console.exe \
  "https://github.com/O/R/releases/download/v3.2.1/Z-MAX_Console.exe"
sha256sum Z-MAX_Console.exe    # 必须等于 digest
```

**并发加速（慢网实测 50~130KB/s 单连接 → 8 并发 ~1MB/s）**:
- browser_download_url 支持 Range；8 并发 × 8MB 分块 + `wait` 收集 + cat 拼接
- ⚠️ 分块 curl 必须带 `-L`：302 不跟随 → 每块 0 字节 → 拼接后整文件 0 字节
  （本会话真实踩坑：两个文件都拼出 0 bytes，sha256 全是 e3b0c442...）
- ⚠️ `pkill -f <pattern>` 的模式别出现在自己命令行里——会匹配到当前 shell 自己并 SIGTERM 自杀；
  杀后台进程用 process 工具或精确匹配

## 2. 验证 --add-data 真打包了资源: PyInstaller archive_viewer

构建绿 ≠ 资源在包里。Linux 上直接解 CArchive 看内容：

```bash
uv pip install --python <venv>/bin/python pyinstaller   # venv 无 pip 时（ensurepip 缺失的系统同理）
<venv>/bin/python -m PyInstaller.utils.cliutils.archive_viewer -l dist/Z-MAX_Console.exe | grep flows
# 输出每行: offset, size, compsize, typecode, name
# 例: 38471255, 4434, 23025, 1, 'b', 'flows\\dual_brain_peg_yolo.json'  → 打包成功
```

## 3. Windows exe 版本号（Linux 上验证）

```bash
uv pip install --python <venv>/bin/python pefile
<venv>/bin/python - <<'PY'
import pefile
pe = pefile.PE("Z-MAX_Console.exe", fast_load=True)
pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
for entry in pe.FileInfo[0]:
    if entry.Key.decode() == "StringFileInfo":
        for st in entry.StringTable:
            for k, v in st.entries.items():
                if k.decode() in ("FileVersion", "ProductVersion"):
                    print(k.decode(), "=", v.decode())
PY
```

## 4. PyInstaller onefile 资源路径: frozen 感知（同发版的前半段修复）

**症状**: exe 主界面能开，加载数据文件（画布 JSON）失败。双根因叠加：
1. `--add-data` 没加资源目录 → 解压目录里没有
2. 源码 `os.path.dirname(__file__)` 上溯找仓库根；frozen 下 `__file__` 在 _MEIPASS → 找不到

**修复模板**:
```python
def _repo_root_path():
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```
- 所有 `__file__` 上溯点都要换（simulink_module.py 13 处、studio.py 3 处、training_backend.py 1 处），
  相同赋值 `repo = os.path.dirname(...)` 用 replace_all 统一替换；缺 `import sys` 的文件要补
- `--add-data` 源路径：PyInstaller 在 tools/gui 下运行，相对路径 `flows;flows`（找不到）、
  `..\flows`（上溯只到 tools/）都失败过 → 用 `$GITHUB_WORKSPACE/flows` 绝对路径
  （Windows `$env:GITHUB_WORKSPACE\flows;flows`，macOS `$GITHUB_WORKSPACE/flows:flows`）
- frozen 验证：模拟 `sys.frozen=True; sys._MEIPASS=<tmp>` + 资源复制到 tmp/flows，
  offscreen 跑加载；再 `del sys.frozen` 回归源码路径。本会话 Z700 33 节点 / ff_pd_top 20 节点加载通过

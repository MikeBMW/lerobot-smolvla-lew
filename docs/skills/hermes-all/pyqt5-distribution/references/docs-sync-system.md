# Document Sync System Reference

Full implementation from `tools/gui/docs_sync.py` (lerobot-smolvla-lew repo).

## Core Architecture

```
静界/                     ← docs root (next to .exe or %LOCALAPPDATA%)
├── .version              ← {version, last_sync, doc_count, hash, zmax_version}
├── 01-培训/               ← Z700F training, product level definitions
├── 02-解决方案/            ← L2, L3 technical solutions
├── 03-训练模型/            ← SmolVLA training, benchmarks
├── 04-运维部署/            ← Orin ops manual, deployment guides
├── 05-开发参考/            ← dev bible, version management
├── 06-发布品牌/            ← product launch, branding materials
├── 07-供应链/              ← supplier docs (Orin, Thor, etc.)
└── 00-其他/               ← uncategorized files
```

## Key Functions

| Function | Purpose |
|----------|---------|
| `get_docs_dir()` | Determine root path (frozen vs source, with fallback) |
| `classify(filename)` | Route file to category by prefix matching |
| `_list_remote()` | Walk GitHub Contents API recursively, return file list |
| `sync()` | Download all files from `raw.githubusercontent.com` to local |
| `push_to_github()` | Push local changes back (API or git CLI) |
| `get_status()` | Read `.version` meta for status display |
| `_compute_hash()` | MD5 of docs dir for change detection |

## Routing Rules (ROUTING_RULES)

```
01-培训:     Z700F, Z-MAX产品等级定义, TRAINING, 产品培训
02-解决方案: L2-, L3-, 解决方案, SOLUTION
03-训练模型: SmolVLA, 训练方案, 数据日志, benchmark
04-运维部署: Orin, 运维, DEPLOY, EDGE, V1.0.6-真机
05-开发参考: HELP-DEVELOPMENT, VERSION, UPSTREAM, ARCHITECTURE
06-发布品牌: L1-, BRAND, 轮式双臂, 立项方案, 竞品分析
07-供应链:   供应链, PRO3000, Thor-, 域控
```

## GitHub API Endpoints Used

- `GET /repos/{owner}/{repo}/contents/docs` — list directory recursively
- `GET https://raw.githubusercontent.com/{owner}/{repo}/main/docs/{path}` — download file content
- Excluded dirs: `source/`, `skills/`, `archive/`, `memory/`, `screenshots/`, `web/`, `test-reports/`, `survey/`, `patents/`

## .version File Format

```json
{
  "version": "v1.0.5",
  "last_sync": "2026-07-30 08:30:00",
  "doc_count": 87,
  "hash": "a1b2c3d4e5f6a7b8",
  "zmax_version": "v1.0.5"
}
```

## Frozen Detection Pattern

```python
if getattr(sys, 'frozen', False):
    exe_dir = os.path.dirname(sys.executable)
    docs_dir = os.path.join(exe_dir, "静界")
else:
    docs_dir = os.path.join(repo_root, "静界")
```

## Menu Items (PyQt5)

```python
act_sync = QAction("📥 同步文档 (从 GitHub 下载)", self)
act_sync.triggered.connect(self._sync_docs)

act_push = QAction("📤 上传修改 (推送到 GitHub)", self) 
act_push.triggered.connect(self._push_docs)

act_open = QAction("📂 打开文档目录", self)
act_open.triggered.connect(lambda: QDesktopServices.openUrl(
    QUrl.fromLocalFile(self.docs_path)))
```

## Notes

- The .exe opens GitHub raw URLs for docs (not local files) in frozen mode
- Push to GitHub from Windows .exe requires GITHUB_TOKEN env var
- API-based push is partial; full bidirectional sync needs git CLI

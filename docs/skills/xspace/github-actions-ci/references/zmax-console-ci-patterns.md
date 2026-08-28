# Z-MAX Console CI Patterns (session 2026-07-30)

## Workflow files committed

### 1. `.github/workflows/build-win-exe.yml`
- Windows PyInstaller build → artifact + Release upload
- Handles both tag push and workflow_dispatch
- Required permissions: `contents: write` for release upload
- Key fix: dedicated `release_tag` step for workflow_dispatch (github.ref_name is branch, not tag)

### 2. `.github/workflows/docker-console.yml`
- Docker build + push to Alibaba Cloud ACR
- ACR vs Docker Hub because China blocks Docker Hub
- Uses `"on"` (quoted) to avoid PyYAML `on:` → True parsing issue

## Zone.Identifier cleanup

4 files found (all under docs/):
```
docs/他山Ⅰ期验收交付件.zip:Zone.Identifier
docs/供应链/Orin域控产品手册3.2版本 - CN.pdf:Zone.Identifier
docs/供应链/Thor-域控产品手册1.0版本 - CN.pdf:Zone.Identifier
docs/智算中枢·智能化技术标准（Q_ZFCY001.1-2026）.pdf:Zone.Identifier
```

Committed as `5a43774 fix: 移除 Windows Zone.Identifier ADS 文件`. Added `*:Zone.Identifier` to `.gitignore`.

## CI run history

| Run | Result | Reason |
|---|---|---|
| 1st (tag push) | Checkout failure | Zone.Identifier on Windows |
| 2nd (tag push) | Release upload failure | Release didn't exist |
| 3rd (workflow_dispatch) | Release upload skipped | Condition failed (ref=main, not tag) |
| 4th (workflow_dispatch) | Release upload failure | Missing permissions.contents: write |
| 5th (workflow_dispatch) | **SUCCESS** | All fixes applied |

## Release URL
https://github.com/MikeBMW/lerobot-smolvla-lew/releases/tag/v1.0.5

# 自动更新系统 (Z-MAX Console)

PyInstaller Windows .exe 的自我升级机制。

## 组件

```
tools/gui/update_checker.py
```

## API

| 函数 | 作用 |
|------|------|
| `check_latest(timeout=8)` | 查 GitHub /releases/latest API → {version, download_url, release_url, published} |
| `download_update(url, path, progress_callback)` | 分块下载 .exe，支持进度回调 |
| `check_in_background(callback)` | 后台线程检查，发现新版本回调通知 |

## 集成点

- **首页**: `⬆ 升级` 按钮（hero 区，橙色）
- **菜单**: 关于 → 🔄 检查更新
- **启动**: `QTimer.singleShot(5000, self._auto_check_update)` 后台无声检测
- **状态栏**: 发现新版本时显示 "📢 发现新版本 v1.0.6 — 关于 → 检查更新"

## 升级流程

1. 检查 → 发现新版本 → 三按钮对话框
2. 用户选「下载并升级」
3. 下载到 `%TEMP%/zmax_update/Z-MAX_Console_new.exe`
4. 创建 `upgrade.bat` 等待 2s → copy → start → self-delete
5. 通知用户重启

## 版本追踪

版本号需在 3 处同步更新：
- `update_checker.py` → `CURRENT_VERSION`
- `version_sync.py` → `zmax_ver`
- `docs_sync.py` → `"version"` in `.version` meta

每次打新 tag 时一起改。

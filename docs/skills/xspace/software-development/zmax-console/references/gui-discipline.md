# GUI 维护纪律与坑 (zmax-console)

## 纪律 (铁律)
- 只 patch 改, 不重写; kill-9 重启
- 本地容器 --gpus all / 远程 --runtime nvidia --gpus all; ssh -o Port
- ID 叠加 QLabel 不 replaceWidget (须 show())
- **主线程禁同步网络请求**: _cam_connect/_cam_poll 曾 timeout 8-10s 卡死 GUI (窗口假死, 进程活着 0%CPU)
  → 子线程发请求 + QTimer.singleShot(0, ...) 回主线程应用 + 防重入标志跳过堆积 tick; 超时 4s

## refs 速查
- wsl-display-links: 飞屏→QT_QPA_PLATFORM=wayland 启动(EGL警告忽略); 开链接=cmd.exe start(Windows浏览器); 深色主题弹窗显式白字 #e6edf3; VEH 序号重排须解释
- simulink-id-and-skill-tokens: 场景双击弹 JSON 上传窗; 原子v4 一键三场景全链
- simulink-flow-json: row_bg 名 ≤8字 + 节点 x ≥ 背景x+160

## 新增坑 (2026-08-10)
- 摄像头轮询假死根因: QTimer 主线程同步 requests.get (timeout 8s) → 网络不通时每 1.5s 阻塞 8s
- 修复模板: `_th.Thread(target=lambda: self._cam_apply_later(_fetch, _apply), daemon=True).start()`
  `_cam_apply_later`: `res = fn()` (子线程) → `_QTM.singleShot(0, lambda: apply(res))`
  ⚠️ fn() 必须在子线程执行, 不能写进 singleShot 的 lambda

## 新增坑 (2026-08-18): 操作视频画布内嵌播放性能
VcXsrv 无硬件加速, 画布每帧重绘 = 狂闪/卡顿:
- 66ms (15fps): 狂闪 (每帧全量重绘跟不上)
- 150ms (6.6fps): 不闪但明显卡顿, 动作不可辨
- **100ms (10fps): 平衡点** — 不闪且动作可辨

解法 (simulink_module.py _mlp_tick / _toggle_mlp_play):
1. 帧率定 100ms (10fps), 别追求 15fps
2. **播放期间暂停 hover 轮询**: `self._hover_timer.stop()` — 减少画布重绘竞争, 视频明显更流畅
3. 暂停/停止时恢复 hover 轮询: `self._hover_timer.start(300)`
4. 所有 timer 操作包 try/except (hover timer 可能不存在)

验证纪律: 改帧率/定时器联动后**必须重启控制台实测** — 用户对卡顿/闪动零容忍 (黑条闪动=连线动画惰性化同理)。

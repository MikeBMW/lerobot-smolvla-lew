# 操作视频方向与生成约定更新 (2026-08-27)

> ⚠️ 覆盖/修正 `operation-video-player-2026-08-18.md` 中的过时结论, 以本文为准。

## rot180 已废弃 (2026-08-23 起)
- 旧结论: "MLP 视频默认 rot=180 画面正" (2026-08-19)
- 现状: gen_insert_video.py 已去掉 180° 旋转 — `env.render()` 原始输出即标准投影方向
  (真值 hand 投影 (237.6,219.2) = YOLO 在 img 原始方向的检测中心; rot180 后 (242.6,260.8) 反而错位)
- **生成端不旋转, 播放端别再默认 rot=180**; 判断方向仍可用 scripts/ocr_dir_check.py

## gen_insert_video.py 输出约定 (2026-08-27 改)
- 成功 seed 渲染 → reports/insert_success_demo.mp4 + **mlp_insert_success_final.mp4 双份**
  (播放器 _PRIORITY 第一/第二; 后者是 reports/*MLP*.mp4 标准名, exe 打包取此名)
- 成功后保持画面 90 步 (~2.7s) 再收尾 — 原 68 步成功只出 35 帧 ≈1.1s 太短
- 帧采样 step%2==0, 30fps ffmpeg 合成; 停滞 120 步换 seed; 全失败回退 BRAIN_CKPT

## 预抽帧缓存 (Windows exe 无 ffmpeg 的解法)
- 播放器缓存 `reports/_mlp_cache_<名>/` 帧数>10 直接播, 不调 ffmpeg
- exe 打包缓存: `ffmpeg -vf "fps=10,scale=960:-2" f_%04d.jpg` (35 帧 ≈900KB;
  播放器 100ms/帧 → 播放时长与视频一致; 全量抽帧 355 帧 59MB 不可接受)
- exe 内置视频全流程 (CI 从 ECS 下载 zip → --add-data) 见 pyqt5-distribution「视频资源打包」

# AOI / 外观质量检测线 — 交接单 (2026-09-24 收工)

## 今天做完的（都已 commit+push 到 `lerobot-smolvla-lew` main）

| # | 内容 | 关键 commit | 证据 |
|---|---|---|---|
| 1 | **质量检测任务头 + 汇总终端窗口**（右键「外观质量检测」打开） | 551f7170 | 离线 12/12 · 真桌面 5/5 |
| 2 | UI v2/v3 重做（修最大化/去挤/接口做成技能按钮/终端页/一键拍照/拍照时间） | 8b3e0ecd · 1334800f | 同上 |
| 3 | **工控机两台 OPT 相机接入**（本机直连 / 经 Orin）+ 真拍取证 | 820533f7 · 9bffa053 | verify_opt_camera 11/11 |
| 4 | **原始图与判据图同屏** + 标定基准可切 | e1e3f4a8 | 真桌面 5/5 |
| 5 | **过曝切除**（工控机拉长图 73% 死白 → 原图自裁） | 2ca8c993 | 饱和 61.5%→5.6% · 死白行 532→0 |
| 6 | **手动框选拉伸 + 短边×2 口径**（拉长不拉成方图） | 9747d96a · 7f7db9c4 | k=1/2/3 → 135/270/405 |
| 7 | **示教点技能**（记住金手指点1 → 一键回位，走 L2 收口） | 43ae662f · 383f9f4b | verify_teach_point 17/17 |
| 8 | 手动框选两个真 bug（被过曝开关挡掉 / 推理帧没跟着换） | 68382aae · 3836cda5 | verify_opt_camera 40/40 |
| 9 | **裁减图实时推飞书**（图片通道，自换 token，只读监听） | cf380c64 | 群里真收到图；监听实推 No_288 ✅ |

## 关键口径（别再走回头路）
- **工控机 `/capture_detect` 返回 200 ≠ 合格** —— 它只表示"拍照成功 + 检测已排队"（异步）。
  **真判决读 `GET /last_result`**（verdict/count/defects/ms/n + origin/topview 文件名）。
- **YOLO 吃的是裁减图**：`detector.detect(topview_path)`（程序 318 行），不是原图。
  裁减质量看 `/crop_info.score`（今天实测 0.4378，偏低 → 影响召回；v4 验收口径 ≥0.95）。
- **判据图来源优先级**：① 手动框选（永远优先，与「过曝切除」开关无关）② 原始图自动裁切 ③ 工控机拉长图（会显式告警）。
- **拉长口径 = 短边 ×2，长边不动**（今天从 8.2× / 方图改过来的）。
- 圈选状态每次拖框落盘 `reports/aoi_console_state.json`（我看不到屏幕，靠这个核对）。
- 飞书发送走**自换 token 直推**，不依赖 gateway 进程内缓存。

## 现场遗留（需人或工控机侧做）
1. **10083 表面相机取图缺口**：该服务只有 `/capture_detect`，无 `/picture` →
   补丁 `docs/patch/opt_surface_10083_add_picture_route.md`（30 行，与 10082 同语义）。
2. **10082 拉长口径**：补丁 `docs/patch/opt_10082_gold_stretch_2x.md`（3 行；4060 侧已不依赖）。
3. **工控机裁减对齐**：score 0.4378 → 建议按技能里的 v4 模板法做到 ≥0.95。
4. **首轮金手指缺陷标定**：用 `reports/opt_view/*_origin.png` + 窗口「🎯 识别金手指并框」→ 建 AOI 数据集 → 训质量检测头 → 同口径对照后切在役。
   ⚠️ 训练口径必须与线上推理口径一致（线上=工控机方图 960×960；我们=短边×2），**先统一再训**。
5. **两套方法结论分歧未定论**：同一张模型输入图，工控机 YOLO=OK，我们启发式=FAIL 3 项
   （划痕/污染/氧化）→ 需人眼 + 同口径留出集判谁漏谁误报。证据 `reports/aoi_compare_20260924_1851/`。
6. **持久化**：飞书实时监听今天是我会话内的后台进程（已停），要常驻需 systemd/cron。

## 点位/技能现状
- `金手指点1` = pos [0.5973108, 0.1426172, 0.641565]，17:53:12 记录（旧值留痕 `reports/aoi_points/金手指点1.history.jsonl`，可回滚）
- 技能 `L2.goto_gold_pt1`「🎯 回到金手指点1」在册（L2 技能库 30 条），已被「📚 工程记忆」节点收录
- 回位：窗口「🎯 回到此点」（默认 dry-run）或 `echo '{"skill":"L2.goto_point","point":"金手指点1"}' > ~/zmax_data/l2_cmd.fifo`

## 复现命令
```bash
cd ~/lerobot-smolvla-lew
./gui-venv311/bin/python tools/opt_camera_client.py --health --cam 1     # 只读体检
./gui-venv311/bin/python tools/verify_opt_camera.py                     # 40 项判据 (只读)
./gui-venv311/bin/python tools/verify_opt_camera.py --authorize         # 含真拍
./gui-venv311/bin/python tools/verify_teach_point.py                    # 示教点 17 项
QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/verify_aoi_console.py
DISPLAY=:0 ./gui-venv311/bin/python tools/verify_aoi_console_real.py
./gui-venv311/bin/python tools/aoi_feishu_push.py --once                # 推最新裁减图到飞书
```

## 备份
`~/zmax_data/release_20260924_aoi/` (25MB): 判据图/裁减图/对照证据/验证 JSON/圈选与点位快照/补丁文档/审计流水

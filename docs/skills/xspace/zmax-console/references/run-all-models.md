# 「运行所有模型」取证配方 (一次把各层真模型都跑起来, 拿逐层证据)

## 一条命令
```bash
cd /home/ubuntu/zmax && ./gui-venv311/bin/python tools/run_all_models.py --caps l2,l3,l4,l5 --steps 150
# 落盘 reports/run_all_models_<ts>.json (每档一行: 步数/done/终点mm/YOLO帧·检出/MLP真身/INTACT真推理/墙钟)
```

档位 = env 开关, 与 GUI 勾选框逐条等价 (GUI 也是设这些 env 再起引擎):

| 档位 | env | 真模型 |
|---|---|---|
| L2 | (默认, vision=True) | YOLO detect_3d 每帧 |
| L3 | `SS_L3=1` | SmolVLA+LEW 策略出动作 |
| L4 | `SS_USE_MLP=1` + 直驱装配 | 前馈 MLP 真身 + INTACT |
| L5 | (无) | planner + 视觉决策 + 事件级认知头 engine_v3 |

## 坑 (全踩过)
1. **headless 的 L4 档, INTACT 不会自己装**。只设 `SS_INTACT=1` 时 `sim._intact_node is None`,
   u_ff 走 analytic 静默回退 → 计数 0 也不报错。必须照 GUI 的装配块调用公用装配器:
   `IntactRuntime(task='pusht', device='cpu')` → `IntactNode(horizon=8)` → `set_goal(reports/intact_goal_frame.npy)`
   → `intact_direct_rollout.install_direct_act(sim, nd, a_mean, a_std, infer_every=1)` → `sim.attach_intact(nd, None)`
   → `sim._intact_drive={'node','rec','state'}` → **pop SS_INTACT**(否则 u_ff 槽位重复注入, 实测 33mm 滑脱)。
   task 名必须 `pusht`(原项目注册表名), 用 'insert' 会解析成不存在的论文 ckpt → trained=False 零动作。
2. **INTACT 真推理数在两个不同的桶里**: u_ff 通道 = `sim._intact_stats['intact_calls']`;
   直驱通道 = `sim._intact_drive['state']['calls']`。读错桶会得 0 并误判"没跑"。
3. YOLO 计数: `_vis['shot']`=出帧数, `_vis['n']`=检出对象数。每帧 2 个目标(peg + OPT_Gold) → n/shot=2.0,
   按百分比报会得出"200%" 的假象。
4. `SceneVLM.ask(image, ...)`: HTTP 路径(DeepSeek/显式)传的是**文件路径**(内部 open+base64),
   传 bytes 会得到 `ValueError: embedded null byte`;本地路径才吃 ndarray。要判真源看返回 `src`
   (`http:deepseek-flash` / `local:Qwen/...` / `rule`=规则回退, 规则回退不算真跑)。
5. `tools/sam3_seg.py --bench N` 走相机源(`--cam local`), 要单图分割用 `--image 帧.jpg --text 概念 --out/--json`;
   实测 1471ms/帧。帧可从 `reports/ss_episode_latest.mp4` 抽: `ffmpeg -i ... -vf 'select=eq(n\,40)' -vframes 1 x.jpg`。
6. 本地推理服务(8790)两个头: `POST /infer {"state": {...}}` → 6 维动作 + yaw;`/health` 的 `infer_count` 是"跑没跑过"的判据。

## 控制台(studio)怎么从命令行驱动
命令通道 = 往 `/tmp/zmax_nav_cmd` 写一行(**文件被取走后会自动删; 文件还在=没被执行**):
`ss_canvas`(切状态空间画布页) · `ss_run`(▶ 运行状态空间仿真) · `ss_3d` · `ds_win` · `overlay_page` · `station_page` ·
`l5_status`(只读, 回写 `/tmp/zmax_l5_interaction/canvas_state.json`) · `l5_interact`(真鼠标点 L5 单选钮 + ▶运行).

- 起停: `bash tools/studio_ctl.sh {start|stop|status}`;窗口名 `XSpace Studio — Z-MAX vX.Y.Z`;
  启动后它会自己后台加载 L2/L3/L4, 日志 `zmax_data/model_autoload/startup_<ts>.log`, 报告 `reports/model_autoload_<ts>.json`。
- 控制台自己那次 GUI 运行会落 `reports/gui_real_run_<ts>.json`(cap/steps/done/insert_mm/yolo_detect_pct).
- 截图取证: `xwd -id $(DISPLAY=:0 xdotool search --name 'XSpace Studio'|head -1) -out x.xwd && ffmpeg -i x.xwd x.png`
  (`import` 没装; `wmctrl -l` 偶发列不全窗口, 用 `xdotool search --pid <pid>` 更可靠)。

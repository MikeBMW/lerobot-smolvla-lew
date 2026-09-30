# L4 · SW 仿真世界引擎链 + SW 实况窗口 (2026-09-13, v5.5.28 ~ v5.5.33)

老倪需求链: ①"把独立的 INTACT 运行环境集成到状态空间, 点运行就能跑 INTACT, 触发开关 = L4"
→ ②"把 stable-world 渲染帧贴进 3D 视图本体" → ③"小窗太小, 独立出来一个正常窗口"
→ ④"L4 档点 ▶运行 时自动把独立窗口弹出来" → ⑤"弹出的视频怎么不动呢?"

## 1. 链条与数据流 (全部真产物)
```
🧪 SW环境渲染图像源 (数据源)  →  🎯 INTACT策略·cube (中间)  →  🌍 SW仿真世界引擎 (硬件层)
        ▲                                                              │
        └──────────── 渲染回流 (闭环) ─────────────────────────────────┘
                                                 └── 🎬 SW渲染视频 (可视化)
```
- 节点/连线: `flows/state_space_obs.json` 文本级插入 (1 row_bg + 4 节点 + 4 连线), 原有 70 节点/72 连线零改动。
- **L4 门控 = 复用档位机制**: 节点落在名字含 `L4` 的 row_bg 色带内 → `_ss_node_cap_level()` 返回 4
  → 只有 L4 档的链会执行。不需要新开关代码; L2/L3 档实测完全不跑 (自动弹窗函数直接 return None)。
- 桥 = `tools/intact_sw_bridge.py` (跑在 `/home/ubuntu/INTACT-JEPA/.venv/bin/python`)。
  与 `paper_runtime/eval.py` 逐行同源: `swm.World` + `load_pretrained` + `PriorOnlySolver` 零搜索
  + `_extract_init_goal` / `_apply_callables` (来自 `stable_worldmodel.world.world`) + `img_transform`
  + StandardScaler(action)。**唯一区别 = 逐帧流式**: 每步写 `frames/step_XXXXXX.jpg` + `status.json`,
  末尾用官方 `save_panel_videos` 出 3 面板 mp4 (agent | dataset | goal) + concat 合集。
- 采样起点与官方 eval 同法 (`np.unique(ep_idx)` → 每回合 `max_start_idx = ep_len - goal_offset - 1`
  → 合法行随机抽 num_envs 个), 所以窗口/视频口径与官方一致。
  ⚠️ **首个坑**: 若自己乱选起点 (episode 0, step 0), 起点可能已经满足 goal → `mode='wait'` 第 1 步就
  终止 (frame=1, steps=1), 看着像 "桥坏了", 其实是数据取样问题。

## 2. 节点逻辑 (node_logic.py 可修改区)
- `_sw_paths(root)` 返回 **(dir, frames, status, video)** —— 解包错位 (`_, st, fr, vd = ...`) 会把 frames
  当 status, 三个节点同时报 "桥进程已退出, stage=None" (静默错误, 排查很痛)。
- `_sw_start(root, log)`: 起/复用桥进程, 日志文件 `reports/intact_sw/bridge.log`, 返回
  `(ok, status, frames, video)`; **已存在活的桥就复用**。
- `_sw_alive()` 判活; `_sw_wait(status, pred, timeout, log, tag)` 轮询终态, 内含
  "进程已退出 → 再读一次终态 → 才判失败并打 bridge.log 尾部" 的兜底 (修 status 写入竞态)。
- 顺序链上 **第一个节点负责启动桥并等到 `stage=='done'`**, 后续节点只读终态 —— 避免节点间竞态。
- 桥必须用 INTACT venv: 仓库 `.venv` 没有 numpy/torch → `ModuleNotFoundError: No module named 'numpy'`
  (症状: bridge.log 报错, status.json 永不出现)。`_sw_python()` 里 INTACT venv 排第一。

## 3. 窗口三形态 (同一数据源)
| 形态 | 实现 | 入口 |
|---|---|---|
| 3D 内嵌小窗 (画中画) | `DreamView3D._sw_panel` = `self.view` 子控件, 150ms 轮询, eventFilter 里随 resize 重贴右上角 | 图层勾选「🎬 SW 实况」 |
| 独立窗口 | `ss_dreamview.SWLiveWindow` (顶层, 父=None, 760×860 可拉伸; ⏸暂停/倍率×1~×4/📌置顶/📂视频目录) | 3D 左侧绿按钮 / 内嵌小窗「⤢ 放大窗口」 |
| 自动弹出 | `_auto_sw_live_window()` 在 `start_sim()` 状态空间分支入口调用; L4 才弹 + 同时 `_sw_start` 真启动桥 | L4 档 ▶运行 |

全局单例: `ss_dreamview.sw_live_window()` → 三个入口共用一个实例 (不会开出两个窗口)。

## 4. 五个实测坑 (按踩到的顺序)
1. **画布载入会重生成 node id** → offscreen 校验必须按**节点名**匹配 (id 查不到)。
2. **`_sw_paths` 解包错位** → 见上, 静默误读。
3. **桥退出瞬间读 status 竞态** → 终态重读 + 进程死亡检测。
4. **▶运行不跑 node_logic** → L4 自动弹窗必须同时启动桥, 否则窗口显示旧帧 = "视频不动";
   排查顺序: 产物时间戳 → 控制台日志痕迹 → 子进程是否在跑。
5. **QLabel.pixmap() 返回对象会随再次 setPixmap 变动** → 测试里比较尺寸必须**立刻取 int**
   (`w1 = int(lbl.pixmap().width())`), 否则 ×1/×4 都读到最后一帧的宽度, 误判"倍率不生效"。

## 5. 验证清单 (可复用)
- 画布拓扑: 节点数/连线数 (只增), 4 条 SW 连线按**名字**匹配, L2/L3 节点仍在。
- 端到端真跑: 清空 `frames/` → 调 `_auto_sw_live_window()` → 断言 桥真起 (pid) / 帧数增长 /
  `status.json` mtime 更新 / 窗口显示帧号变化 (画面在动) / 日志有启动记录。
- 窗口: 面板存在 / 勾选框在位 / 贴真帧 (像素 std>5) / 状态行真值 / 关→隐藏 开→显示 /
  小窗在视口内 / 整窗 `grab()` 非全黑 + 存 PNG 作证据。
- 版本: 五处同步 (studio.py 窗口标题+QLabel+changelog / update_checker / version_sync / docs_sync×2 / VERSION.md)。

## 6. 实测数字 (留档)
- 端到端链条: 13.6s / 3 回合 / 52 帧 / frame_std 30.26 / 模型真调用 52 次 / 零搜索
  (candidate_action_steps=0) / 4 个视频文件; 每帧 224×224 EGL 离屏。
- 桥单独跑 3 回合: 加载 ~11s + 52 帧 ~3s; 视频 736×288, 逐回合 mp4 + showcase 连播。

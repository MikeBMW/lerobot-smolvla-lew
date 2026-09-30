# 控制台「🌐 全局数据空间」页 —— DDS 全链路 topic 可视化 + 数据闭环 (2026-09-29)

## 页面结构 (改完后)
`tools/gui/studio.py::DataSpaceModule` (原 3434 起) 现在是一个 **QTabWidget，5 个 Tab**：
```
🗂 全息映射 (节点↔数据对象)   ← 原有的 node↔产物 表 (依然在 Tab 0)
📡 频道 (topic)               14 行: 话题/类型/实测Hz·设计Hz/帧龄/条数/配对/裁决/本档+问题
🔁 数据闭环                   9 行: 每环节 裁决 + 门 + 证据
⚠ 质量告警                    规则不过的频道 + 闭环 fail
🔎 字段真值                    选中频道的**最新字段值**(JSON, 可复制)
```
头部条(由 `dds_space.build_widget(parent, into_tabs=...)` 返回): 档位下拉 + 切换 + 刷新 + 导出 CSV + 复制 JSON。

## 为什么做成 Tab 而不是新模块卡
老倪投诉过「一个功能一个入口，绝不重复」(CICD 全链路 vs 数据闭环控制台、验证/集成按钮都重复过)。
新增 DDS 能力时：**嵌进已有页的 Tab**，不要开第 13 个模块卡；也不要嵌套 Tab（`build_widget(into_tabs=…)` 就是为这个做的）。

## 数据源（不许本页自己采数据，避免第二处口径）
```
/home/ubuntu/zmax_data/dataspace/live.json   ← zmax-dataspaces-probe.service (DDS→JSON 桥, 2s)
/home/ubuntu/zmax_data/dataspace/loop.json   ← zmax-dataspaces-loop.service (闭环九环节证据, 15s)
/home/ubuntu/zmax_data/dataspace/busdb.json  ← 画布导出的 DBC (74 节点/182 信号/14 报文)
/home/ubuntu/zmax_data/dataspace/trace.jsonl ← 总线帧流 (每行一条, 含真 payload digest)
src/lerobot/dataspace/topics.py              ← 注册表(话题/类型/QoS/生产者/消费者/闸门/质量规则)
```
页面**不需要 cyclonedds**（主 venv 里也没有，别装）。

## CANoe 范式重做 + 独立窗口 (2026-09-29 晚)
- 该页从「12 个 Tab 堆叠」改成 **CANoe 主窗口范式**: 新模块 `tools/gui/dds_canoe.py::build_view(main_win)`
  = 测量组(⚡Start/⬢Stop) + 左 Data 信号表 + **中 Trace 整宽** + 右详情 + 底 `🔁 数据闭环 | ⚠ 质量告警` 页签;
  旧的 12-Tab 视图收进右上「🗂 经典视图」开关(`main._canoe_classic_cb` 切显隐) ⇒ **旧入口零丢失**。
- **独立窗口**: `build_view(None, standalone=True)` 塞进一个**无 parent 的 QMainWindow**(见 SKILL.md 的窗口类型条目),
  由状态空间画布页工具条的「🌐 数据空间窗口」打开 ⇒ 跑 L5 画布/3D 时同屏看 topic 实时值。
  standalone 模式要**隐藏「🗂 经典视图」开关**(它依赖主窗口的 Tab 容器)。命令通道: `printf 'ds_win' > /tmp/zmax_nav_cmd`。
- ⚠️ 高频自刷新的表格 **禁用 `ResizeToContents`**(逐格量列宽 → 整核 CPU), 详见 SKILL.md 那条。

## 🔎 「某节点的输出是哪个 topic?」怎么查 (先查真源, 别凭印象答)
四步，全部可在本机文件里查证：
1. **设计态(注册表)**: `busdb.json` 的 `signals[]`，每条 = `{sid, src, src_port, dst, dst_port, label, layer, topic, link_id}`。
   **判据: `src` == 目标节点的那条就是它的输出连线; `topic` 字段才是它挂的话题。**
   例: `S151 src=n_moveit → dst=ssact`, `topic=zmax/link_value`, `label=轨迹 → 执行 (SDK桥 / ROS2 SRV)`。
   ⚠️ 全图连线走**同一条已注册报文 `zmax/link_value`**，信号身份 = **(src, port)** —— `dds_link_bus.py` 头部注释里的
   `zmax/link/<node_id>` 是早期设计, 别照它回答; 以 `busdb.py`/`busdb.json` 为准。
2. **实测态**: `live.json` = 每话题实测 hz / 帧龄 / 条数 / 裁决。**`hz = -1` == 这一档没在发**(不是坏了、不是卡)。
3. **内容**: `trace.jsonl` 每行 `{t, topic, type, n, bytes, digest}`，`digest` 是该帧真 payload。
   例 `zmax/ss_action` = `{"ts":…, "kind":"joint", "joints":[6 维], "tcp_pose":[], "gripper":-1, "speed":-1, "gate_pass":…}`。
4. **谁在发**: 注册表 `producer` 字段 / `tools/dds/ss_daemon.py` 头部注释。`ss_state|ss_action` = ss_daemon 从真机只读 tap
   `~/zmax_ss_remote/{state,proposal}_*.jsonl` 取样(**不是**引擎直接发 DDS)。

⚠️ **键名口径坑(踩过, 会让整列显示「—」)**: `live.json` 的键是**短名**(`ss_action`)，`trace.jsonl` 的 `topic` 是
**全路径**(`zmax/ss_action`) ⇒ 任何"按话题 join"的列(如 `Last Value Time [s]`)必须先归一化(剥 `zmax/` 前缀),
否则永远落空。

⚠️ **别把 ROS2 服务当 DDS 话题答**: MoveIt2 的规划输出接口是 ROS2 **服务** `/plan_kinematic_path`
(+ `/compute_ik` `/compute_fk`，见 `tools/moveit_plan_only.py`；目标容器 `allow_trajectory_execution=False` = 只规划不执行),
**它不产生 DDS 话题**; 真机执行走 `arm_control.py` 的 `ArmController`(Orin SDK 直驱桥 / ROS2 SRV 双后端)。
查"在不在跑": `docker ps` + `pgrep -af move_group` 为空 = 没起 ⇒ 任何"MoveIt 输出"都不会有新值。

**回答口径(三件一起说, 否则被当成"卡住了")**: ①设计态那条连线挂哪个话题 → ②现在实测有没有在发(`live.json`) →
③它上游那一级(如 MoveIt 本体/子容器)此刻有没有在跑。缺任何一件, 用户会在一个永远不更新的字段前面白盯。

## 复核后整改(2026-09-29, 已入库 f9b58fa0)
- 灯墙分组标题与卡片同格 ⇒ 叠字: 半行未填满时标题必须 `gr += 1`。
- 统计表末列 `Stretch` 会吃掉 43% 宽度(裁决列 712px 全空): 让内容列(报文)拉伸, 其余 `ResizeToContents`。
- 报文框要 y=16..busY-8 才装得下 4 行文字(第 4 行曾被框底切)。
- 全黑灯墙必须配一句“本档无节点间数据流=预期, 点回灌可点亮全图” —— 否则 74 盏黑灯被老板读成“系统挂了”。
- 质量页别出 `门=None/None` 这种半成品字样(拿不到 gate 就给 `-`)。

## 改这个页面的踩坑与铁律
- **重启纪律**：改 GUI 必须重启才生效，但重启是代价最高的动作。流程 = 作业前备份 → offscreen 自检 → **一次**干净重启 → 汇报带新 pid + 启动时间。`zmax-studio.service` 必须是 `Restart=on-failure`（曾 `always` 导致关窗口被反复拉起）。
- **offscreen ≠ 现场字体口径**：现场 `Xft.dpi=192`，offscreen 跑 96dpi ⇒ offscreen “全过” 不能当字体不裁的证据。
- **按钮必须 addWidget**：对象存在 + text() 对，但没挂布局就是界面不可见且不报错。自检断言 `btn.parent() is not None`。
- **主线程不碰网络**：live.json/loop.json 是本地文件读取，主线程 QTimer 刷新没问题；**ECS/8790/SSH 请求必须进后台线程**。
- **prod 档要显式标注**：量产档 `prod` 不发任何 DDS 话题是**预期正确**（零开销），页面要显示“本档允许 0 话题 + 原因”，否则会被误判成坏了。
- **扫描根目录**：`tools/gui/data_space.py` 原扫 `~/lerobot-smolvla-lew`（另一棵分支检出），已改 `ZMAX_REPO`(默认 `/home/ubuntu/zmax_rel`)——老倪红线：逻辑与产物只有一个 CICD 路径。

## 相关服务
```
zmax-dataspaces-probe.service  (dds-venv)       → live.json
zmax-dataspaces-loop.service   (lerobot-venv)   → loop.json
zmax-dds-pub / zmax-dds-agg /zmax-dds-ss.service (现有 DDS 三件套)
```

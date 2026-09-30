# L5 档位「标注 → 训练」闭环 (画布侧机制)

用途：能力档位节点选 L5 后点 ▶运行，后台跑「视觉语言自动标注 → 监督数据 → L2/L3/L4 训练 → merge」，
并把状态回画布；以及「重启后自动加载在役权重」这条链。改这条链或排查"点了没反应"时看这里。

## 状态真源（只有一份，不要造第二套数字）
`~/zmax_data/l5_loop/state.json`
```
status     running | done | failed
stage      当前阶段名 (interact/annotate/supervision/slots/L2_full/L3_lora/L4_lora/merge/verify)
stages_done[]            已完成阶段
results    {<阶段>: {ok, secs, reason, batch, supdir, ckpt, ...}}
pid        编排进程自身 pid        ← 判"在不在跑"用这个
stage_detail {name, pid, lstart}   ← 子进程 pid 只在阶段内有效, 阶段间隙会空/误判
updated    时间戳
```
日志与锁：`~/zmax_data/l5_loop/*.log`、`loop.lock`（单实例闸门，防重复点击抢 8G 显存）。

## 阶段顺序与红线
- 第 0 阶段 `interact` = 人机交互：复用 `hil_bridge.build_snapshot/handle_instruction` + `tools/hil_local_api.py:8795`，**不另造一套交互通道**；
  落 `interact_state.json`，红线文案固定为「只读: 读TCP/抓图/记录/标注; 不动臂」。
- 串行跑（8G 显存同刻只允许一个模型进程），2~6 路相机逐路调视觉大模型，每路 30~180s 属正常，GUI 侧必须异步（子进程），不许阻塞 UI 线程。
- 视觉语言调用 `max_tokens≥3000`，调用方 timeout ≥300s（否则 content 空、会被判不安全）。

## 反假训练三道闸门（缺一条就会给出"假成功"）
1. **标注 0 框 ⇒ 判失败**并写清原因，原因要分三类：没拿到帧 / 模型返回空(超时、max_tokens 不足、图过暗) / 模型认了但都不在类别表(带 skipped_labels)。
   判据是 `mapped_boxes>0` 且映射后无空标签/越界，不是"跑完了"。
2. **训练启动前断言数据集非空**（train/val 的 labels 文件数与非零框数 > 0），否则**拒绝启动**（state 里 cmd 留空，进程一次都不许起）。
   症状对照：空集上也照样打印 `8 epochs completed in 0.001 hours` 并"成功"。
3. **训完要真推理验证**：跑一遍真帧，0 框 ⇒ 记为**不算成功 / 权重不可用**，即使训练器自己的日志写着 `✅ 完成` —— 闭环的判据要覆盖工具的自报。
4. **换在役不自动**：`tools/l5_promote_l2.py` 默认只做"回退风险校验 + 打印命令"，`--check-only` 先比新/旧模型真帧检出数，`--yes --force` 才实切。

## 在役权重的换法（reboot 自动加载链）
- 换在役**走软链，不覆盖文件**：`models/yolo_peg_live.pt` → `ln -sfn <新 best.pt> models/yolo_peg_live.pt`（回退就是再指回旧的）。
- 自动加载真源 `models/active_models.json`，入口 `tools/model_autoload.py`；
  挂钩在 `tools/gui/studio.py` `main()` 里 `app.exec_()` **之前**，且必须是**独立子进程**（lerobot/metaworld 的 import 链带 GIL/GPU，线程里跑会拖死 GUI）。
- 验证一条命令即可：`./gui-venv311/bin/python tools/model_autoload.py --only L2` →
  期望 `✅ L2 已加载 · <权重路径> (Xs) · 类别 [...] · 真帧检出 N` + 一份 `reports/model_autoload_*.json`（判据字段写"全部就绪"）。
- 启动日志落在 `~/zmax_data/model_autoload/startup_*.log`；判"重启自动加载通没通"就 grep 这行：`🧿 重启自动加载: L2 YOLO / L3 SmolVLA / L4 INTACT 后台子进程已启动`。

## 槽位标注（把"演示"变成监督数据）
`tools/l5_slot_tool.py` + 登记表 `models/l5_slots.json`（14 槽位，未演示的如实写"未演示"，不许补假数据）：
1. 用户把光模块放进槽位的那一刻：记 **TCP 真值**(base_link, 带 age) + 三路实拍帧（时间戳对齐）。
2. 用已标定的投影（相机内参 K + 手眼 T_cam2tool）把 3D 投成画面角点，产出 `center_uv / box_uv / corners_<cam>.jpg`。
3. **再让视觉大模型复核框是否真贴合槽位边沿**；判定不一致 ⇒ 记 `status=待确认`，**不静默修正**。
   建集默认只收 `已记录`，`--include-pending` 才带自检样本。
4. 落成 YOLO 数据集 `data/yolo_annot_l5slots/dataset/data.yaml`（`nc=14`，`slot_01..slot_14`，标签走 `labels/<name>.txt` 的 xywhn）。

坑：
- **角点投影用的是"物体几何"，不是"槽位几何"** —— 拿光模块的 40×16×12mm 去投，框会偏上、贴不住槽位边沿。要槽位内腔尺寸(宽×高×深)或槽位排布才能贴准；拿不到就用用户每次落点的 TCP 反推。
- **相机每帧可能移动** ⇒ 不能一次性标定；每次都要重新检板/检基准物再解算。
- 有深度路时用深度定 z；**深度路断时可用"已知尺寸的基准物"(如四角各放一个 40mm 宽的光模块)从图像定 mm/像素标尺**，不依赖深度相机。

## 汇报口径
给"**进程 pid + state.json 的 status/stage + 产物路径+时间戳**"三处，不要只说"已在跑"；
产物图要能打开（标注图 + 框 JSON 原样贴 label/conf/box），低置信(<0.5)要标出来，没检出就说没检出并给原因，不许编。

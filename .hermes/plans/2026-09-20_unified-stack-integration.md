# Z-MAX 五层联合运行 + 可训练 集成计划

老倪 2026-09-20 指令原文要点：
> 你要修好真机视频流；你现在正在料盘上方，有两个光模块，分别在一号位和二号位；你要全局打通
> 大语言模型层、L4 INTACT、L3 SmolVLA、L2 前馈加速器(根据 YOLO 2D→3D 深度)、统一状态空间，
> 进行原子动作的控制；大语言模型层的 DeepSeek VL 要先看到场景(Qwen 下载好了么，也要应用，
> 你来切换推理模型)，看到两个光模块，指导 L4/L3/L2 功能：L4 意图导航、L3 流程安排、L2 执行；
> 你来进行整体训练，包括 INTACT 微调、SmolVLA 的 LoRA 微调、Flow-Matching 微调等，即所有模型
> 要一起联合运行，且可以训练；这是个系统工程，做好计划，按步骤，全部都要完成；
> **先不要在真机发出指令**（已手动模式），可以看、读、变、训练、推链、联合调试。

## 铁律（本轮不可越界）
1. **不发真机指令**：l2_daemon 不投条、不改 robot_status、不调 motion/hmi/state_machine。
2. **不动产线代码/不加程序到 Orin**：只读探测(话题/服务/日志/参数/文件)。
3. 验收要证据：JSON/日志/视频/数值，画面自身要标状态（帧龄/横幅）。
4. 判据用真值（话题直读），不信任缓存；模型必须被真实链路**每帧调用**才算接上。
5. 磁盘红线 300G（当前 301G/76G 富余）→ 训练产物只留最后 ckpt。

## P0 真机视频链路（当前断点）
现状（实测）：
- Orin 相机节点进程活着(`realsense_source` pid 4694, 自 09-16 16:17)但**全线程 futex 僵死**，
  ROS 图里已消失 → `/realsense/color/image_raw` **Publisher count 0**。
- 它握着 6 个 /dev/video*（独占打开），硬件(RealSense D405, USB 8086:0b5b)本身正常。
- 该节点在产线 launch 里是**普通 Node（无 respawn / 非 required）** → 杀掉不会自愈，
  也不会带崩线体；恢复=**产线侧重启相机节点或整条 launch**。
- 我这侧无责且自愈：`tools/ss_remote_tap.py` 已订阅 raw 图像（1Hz 解码落 `~/zmax_ss_remote/cam_rs.png`），
  来帧即恢复；`SS_VLM` 帧龄闸门 10s。
- 备选眼睛（无需动 Orin）：①本机 video0 相机；②工控机 10082 图片服务；③DeepSeek/Qwen 判读任一可用帧。

产物：①视频恢复（cam_rs.png 帧龄 <10s）②取帧看门狗(帧龄横幅) ③Orin 侧最小重启指令单(待老倪 Go)
验收：连续 60s 帧龄 ≤2s + 一张真帧经 VLM 判读「看到两个光模块」。

## P1 L1 大模型层（DeepSeek-Vision + Qwen 双路）
- Qwen2.5-VL-3B-Instruct 权重**已就位**：`~/zmax_data/hf_home/hub/models--Qwen--Qwen2.5-VL-3B-Instruct`(7.1G, 2 分片, 无残片)。
- 现有管道：`src/lerobot/policies/left_right/state_space/scene_vlm.py`
  优先级 = SS_VLM_URL/KEY > DeepSeek(本机已配 key, deepseek-flash 支持 Vision) > 本地 worker(`tools/vlm_worker.py`)。
- 要做：①本地 Qwen worker 加载验证(离线) ②一键切换推理模型(SS_VLM_PROVIDER/model) ③双路同帧对照
  ④场景判读结构化落 `data/scene_state.json`(目标/位置/朝向/在夹爪上/画面质量) ⑤判读结果**喂 L4/L3/L2**。
验收：同一帧两模型各自输出 JSON + 与几何真值(一号位/二号位)一致或明确报不一致。

## P2 L2 感知：YOLO 2D → 3D 深度 → 统一状态空间
- YOLO 在役权重 `models/yolo_peg_live.pt`(软链)；节点 `tools/ss_yolo_on_real.py`(读 cam_rs.png)。
- 2D→3D：反投影只允许一份 `estimate_3d`；需要 K + 手眼 + plane_z（缺则 z7=null 拒算，绝不编造）。
- 产物：①3D 定位自检(与 slot1/slot2 真值对账) ②obs 组装（cur/prev/target, 逐维 stats 同源）
  ③深度来源口径统一（勿用 depth 话题全帧 2-3m 的旧坑）。
验收：两模块 2D 框 + 3D 坐标，与一号位/二号位真值差 <2mm（标定合格时）。

## P3 L4 INTACT（意图导航）
- 权重：`~/INTACT-JEPA/checkpoints_hf/INTACT-unified`；直驱口径 `install_direct_act→run_once`；
  前馈 MLP 须 `SS_USE_MLP=1`。CPU 影子跑：`SS_L3_DEV=cpu`。
- 要做：①离线加载验证 ②意图/潜空间导航输出接统一状态空间 ③安全闸门(否决/限幅)由 L2 收口。
验收：真权重每帧被调用(日志逐帧计数) + 意图序列落盘可回放。

## P4 L3 SmolVLA（流程安排 + 微调底座）
- 权重 `HuggingFaceTB/SmolVLM2-500M-Video-Instruct`(5.7G 在) + SmolVLA 策略头；
  LoRA 微调脚本 + flow-matching 微调脚本；长程序列输出接 L2 原子技能。
验收：LoRA 前后同口径对照(有提升或如实报无提升) + 序列可执行性检查(技能名全在注册表)。

## P5 训练（三路可训练）
- INTACT 微调 / SmolVLA LoRA / Flow-Matching：数据=真机示教(一号位/二号位/插入/拔出) + 仿真回放。
- 纪律：启训前 nvidia-smi 协商；足 epoch 足数据；终端全打印；跑一次存一次。
验收：三份 ckpt + 训练曲线 + 同口径评测（评估铁律：/255+ImageNet、stats 同源、零回退）。

## P6 联合运行（一图到底，可训练）
- 一条链：帧 → L1 判读 → L4 意图 → L3 流程 → L2 原子技能/前馈 —— 单一进程内联合，可一键起/停。
- 真机只读影子：位姿/力/夹爪开度入 obs，但**不投条**。
验收：连续 N 帧日志证明五层每帧都被真实调用（无短路、无写死、无假值）。

## P7 交付
- 证据留档 `~/zmax_data/<日期>_<主题>/`(MANIFEST+sha256) + docs/memory 同步 + commit/push + 技能沉淀。

## 当前状态（开工基线）
- 版本 v5.11.2 · git main 最新 6f50ef6d(pushed) · 工作树 clean
- 真机：power=on · idle · has_error=false · 手动模式(老倪) · 臂在料盘上方
- 注册表：L2.slot1/slot2/forward/backward/left/right/lift/lower/lissa_insert/lissa_search/pull_module + 9 条 AOI
- 未决：L2.pull_module 合爪未夹住（老倪："不对，没抓住"）→ 需示教 ring_pose 后重建

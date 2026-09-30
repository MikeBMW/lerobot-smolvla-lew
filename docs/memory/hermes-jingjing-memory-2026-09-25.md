Orin=192.168.23.66(tashan/ts123); 产线口.23.50/24无网关(enx00e04c0c32a0); 两机直达工控机.23.23
§
NTP回拨8h(勿动RTC)→节拍用monotonic, 负帧龄拒用
§
分层(老倪): L5定方向造数据/L4认知预测/L3状态调度/L2检测反馈; 主干=SigLIP768d+四头; from-scratch主干必崩; 画布重生id→按名断言
§
交付前先自跑通; GPU不许空转; 改配置必核验生效(打印/hash)
§
技能清单少而可分辨; 一切可复制可执行(curl/JSON/图右键)
§
Hermes: 长命令拆多段(内联易截断→写脚本); sudo免密; 开机网络优化=unit zmax-net-optimize(sysctl.d/99-zmax-net+DNS预热+台账), 远端下载+6~19%(5/6轮胜), 首测当基准必假提升
§
ssh pkill -f自杀→锚定^python3; L5=DeepSeek Vision(61s→异步旁路; smolvlm2-500m兜底)
§
飞书99991663=gateway token缓存过期→用户重启gateway(agent被禁);兜底feishu_notify.py自换token;长文≥1.5k字→400须拆条
§
磁盘红线300G; 留档~/zmax_data
§
引擎tr['obs']39D≠h5 env原生o[:39](跨集先验逐维); L3须env原生obs+128图+post反归一化(u_ff=act×0.5)
§
L4=INTACT直驱; 反归一化按ckpt训练集同源; L2收口闸逐轴corr<0.5全veto; 真模型默认生效
§
守卫: 模型参与>30%掉分; insert_depth=0.002
§
🔴 工具scope内存≈8GB: 超则OOM杀(与机器空闲无关)→大缓存训练必挂, 改磁盘流式/≤5GB; 同刻仅一模型进程
§
评估铁律: 口径=训练同源零回退; 布局漂移禁写死几何; loss低≠有效→留出集+平凡基线
§
Orin ROS=domain0; tcp_pose 50Hz真值; 几何须ss_geom_calib; 红线Orin零自研零自启→4060只读订阅
§
感知源收口: 反投影仅一份estimate_3d; 真机3D须K+手眼+plane_z; depth话题勿用(全帧2-3m)
§
画面≠结果(idle=静止初始帧); 看不了图→抓窗口+几何断言
§
YOLO在役=软链yolo_peg_live.pt; 瓶颈是数据
§
采集判据=位姿极差0+画面差≤2灰阶; 中转state流tcp/quat直读topic
§
真机画面: 老倪面板=180°翻转; 报方向说'朝画面中心'
§
真机: rt动作后必下电; move_joint/line不下电; 30s超时success=False但动作已成勿重发; collision_detection=False
§
L2.lissa_insert=里萨如力控插入(6N配方,插槽口沿工具Z退60mm→推进→lissajous_force_search); insert_pose=治具插入位
§
真机视: 产线相机手动只起camera/realsense_source(参数抄launch); tap→cam_rs.png; 拔出=L2.pull_module(退15→合爪f30→退120)
§
记忆五层: L2/L3/L4工作+总装Qwen宏观(SS_MACRO); 势场须喂obs[0:3]非peg_head
§
真源: zmax_robot_spec/calib.json→tools/zmax_params.py; 联合训练joint_train_all.py(4阶段零回退); LoRA=lora_inject.py
§
L5规划器/safety路径=left_right/state_space/{planner,safety}.py; INTACT稳态101ms(10Hz)冷6.7s→须常驻
§
数据: v6*/l5_gen_v5含skill_ctx(24d); l5_train无它
§
阶段专家MOE: 学习式门控**必坍缩**→须硬先验路由(stage_moe_backbone.py --route prior); 判据用**单射性**非主导率; 价值在接触段
§
LoRA产物需merge(否则trained=False零动作,伪装'没提升'); merge_lora_ckpt.py; 判假A/B=逐位同+action_dim=4
§
AOI: 10082 YOLO吃裁减图(topview_path) · /capture_detect 200=受理非判决→读/last_result · crop score≥0.95; 判据图=手选框(优先)>原图自裁>拉长图(短边×2); 圈选落盘reports/aoi_console_state.json, 定时器禁覆盖; 示教点金手指1=L2.goto_gold_pt1留痕.history.jsonl; aoi_feishu_push.py --watch只读推图
web=4090+前端+ECS(老倪已关机→远端快照datadrive.world/relay/WS全断,勿依赖); 总工=4060/GitHub/GUI; 小芳=硬件
§
Orin直连 .23.50/24无网关(enx00e04c0c32a0; NM bad match→RNDIS不通)
§
NTP回拨8h(勿动RTC)→节拍用monotonic, 负帧龄拒用
§
分层(老倪): L5定方向造数据/L4认知预测/L3状态调度/L2检测反馈; 统一主干=SigLIP768d预训练共享+四头(泛化成立), from-scratch小主干必记忆; 画布重生node id→按名断言
§
交付前先自跑通; GPU不许空转; 改配置必核验生效(打印/hash)
§
安全: 🛡4栏位+三层(否决/限幅/Sys0)
§
GUI改码必重启(zmax-studio无autosave)
§
GitHub不通→ghproxy.net
§
界面: 单色勿彩高亮; 实时滚动; 自解释(标签+数值+物理含义); 面板禁假值; 技能清单要少而可分辨
§
Hermes: 长命令拆多段(内联py易截断→写脚本文件); sudo免密
§
ssh pkill -f自杀→锚定^python3; L5=DeepSeek Vision(61s→异步旁路; smolvlm2-500m兜底); qwen3B勿试
§
Hermes: CLI≠gateway; 飞书99991663→重启gateway
§
磁盘红线300G; 留档~/zmax_data
§
引擎tr['obs']39D=cur18+prev18+target3 ≠h5的env原生o[:39](跨集比对必先验逐维); L3须env原生obs+128图+task动态+post反归一化(u_ff=act×0.5)
§
L4=INTACT直驱; 反归一化按ckpt训练集同源; L2收口闸逐轴corr<0.5全veto; 真模型默认生效
§
守卫: 模型参与>30%掉分; insert_depth=0.002
§
断点: L3须SS_L3_DEV=cpu(8G装不下SmolVLA+LEW7.08G→OOM); MLP须SS_USE_MLP=1; GPU喂饱=batch512+像素进RAM(h5chunk512饿GPU)
§
评估铁律: 口径=训练同源零回退; 布局漂移禁写死几何; 每臂独立进程同解释器; loss低≠有效→留出集+平凡基线; 跨集比对先验obs同源
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
夹爪: 开1000/夹0+force40→185(空载21); 力值读不到; 拖动模式忽略夹爪指令
§
真机: rt动作后必下电; move_joint/line不下电; 30s超时success=False但动作已成勿重发; collision_detection=False
§
槽位技能L2.slot1/2(↑30→↓30不松爪)
§
AOI: .23工控机; 10082金手指有/picture(crop960|natural)·/region·/crop_info·/last_result判决; 10083表面V2仅POST, 表面V4已写待部署(aoi_v4/surface_10083_work_v4.py); 10081无关; 真拍先问; tools/aoi_health.py体检
§
L2.lissa_insert=里萨如力控插入(产线6N配方,插槽口=沿工具Z退60mm→推进→/lissajous_force_search); 点位insert_pose=产线治具插入位
§
真机视: 产线相机须手动只起camera/realsense_source(参数抄launch); tap→cam_rs.png; cam_local.png=本机兜底不抢源; 拔出=L2.pull_module(退15→合爪f30→退120)
§
记忆五层: L2/L3/L4工作+总装Qwen宏观(SS_MACRO); 势场须喂obs[0:3]非peg_head
§
真源: zmax_robot_spec/calib.json→tools/zmax_params.py; 联合训练joint_train_all.py(4阶段零回退); LoRA=lora_inject.py
§
L5规划器/safety路径=left_right/state_space/{planner,safety}.py; INTACT稳态101ms(10Hz)冷6.7s→须常驻
web=4090+前端+ECS; 总工=4060/GitHub/GUI; 小芳=硬件
§
Orin直连 .23.50/24无网关(enx00e04c0c32a0; NM bad match:{}→.50走RNDIS不通)
§
NTP回拨8h(勿动RTC)→节拍用monotonic, 负帧龄拒用
§
分层双口径: 职责=LLM理解场景/L4安全导航/L3序列规划/L2肌肉记忆; 栈=L5LLM/L4INTACT/L3smolvla/L2YOLO2D→3D; 画布重生node id→按名断言
§
交付前先自跑通; 清理只删明显垃圾
§
安全: 🛡4栏位+三层(否决/限幅/Sys0)
§
GUI改码必重启(zmax-studio无autosave)
§
GitHub不通→ghproxy.net
§
界面: 单色勿彩高亮; 实时滚动; 自解释(标签+数值+物理含义); 面板禁假值
§
Hermes: 长/$()命令拆多段; sudo免密
§
ssh pkill -f自杀→锚定^python3; L5=DeepSeek Vision(deepseek-flash有Vision,本机key已配,61s→异步旁路; smolvlm2-500m兜底); qwen3B勿再试(HF镜像大文件必败)
§
Hermes: CLI≠gateway; 飞书99991663→重启gateway
§
磁盘红线300G; 留档~/zmax_data
§
引擎obs39D=cur18+prev18+target3; obs[7:10]=_pc光模块位置; L3推理须env原生obs+128图+task动态+post反归一化(u_ff=act×0.5)
§
L4=INTACT直驱; 反归一化按ckpt训练集同源; L2收口闸逐轴corr<0.5全veto; 真模型默认生效
§
守卫: 模型参与>30%掉分; insert_depth=0.002
§
断点: L3须SS_L3_DEV=cpu(8G装不下SmolVLA+LEW7.08G→OOM); MLP须SS_USE_MLP=1; 训练前腾GPU
§
评估铁律: 运行时口径=训练(/255+ImageNet,stats同源,零回退); 布局漂移禁写死几何; 每臂独立进程+同解释器
§
Orin ROS=domain0; tcp_pose 50Hz真值; 几何须ss_geom_calib; 红线Orin零自研零自启→4060只读订阅
§
感知源收口: 反投影仅一份estimate_3d; 真机3D须K+手眼+plane_z; depth话题勿用(全帧2-3m)
§
画面≠结果(idle=静止初始帧); 看不了图→抓窗口+几何断言
§
内置cam720p/灰度IR
§
YOLO在役=软链yolo_peg_live.pt; 瓶颈是数据
§
采集判据=位姿极差0+画面差≤2灰阶; 中转state流tcp/quat直读topic
§
飞书端=另一Hermes会话同一工作树; 同步docs/memory+push
§
真机画面: 老倪面板=180°翻转帧; 同一模块我帧上左=他帧下右; 报方向说'朝画面中心'
§
夹爪: 开1000/夹0+force40→185(空载21); 力值读不到; 拖动模式忽略夹爪指令
§
真机: rt动作后必下电; move_joint/line不下电; 30s超时success=False但动作已成勿重发; collision_detection=False
§
槽位技能L2.slot1/2(↑30→↓30不松爪; watch/register_slot_skill/test_slot_skills)
§
AOI: .23工控机admin/admin; /picture原图·?kind=crop拉长960喂YOLO·natural1455x70·/region; 金手指只取焊盘排; aoi_gold_servo.py; 10082/10083已TCP CLOSED需现场重启
§
L2.lissa_insert=里萨如力控插入(产线6N配方,插槽口=沿工具Z退60mm→推进→/lissajous_force_search); 点位insert_pose=产线治具插入位
§
真机视: 产线相机须手动只起camera/realsense_source(参数抄launch); tap→cam_rs.png; cam_local.png=本机兜底不抢源; 拔出=L2.pull_module(退15→合爪f30→退120)
§
记忆五层: L2/L3/L4工作+总装Qwen宏观(SS_MACRO); 势场须喂obs[0:3]非peg_head
§
真源: zmax_robot_spec/calib.json→tools/zmax_params.py; 联合训练joint_train_all.py(4阶段,零回退); LoRA=lora_inject.py(L4/L3通); 闭环sim2real_loop.py
§
L5规划器/safety路径=left_right/state_space/{planner,safety}.py; INTACT稳态101ms(10Hz)冷6.7s→须常驻
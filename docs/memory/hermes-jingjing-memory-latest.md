web=4090+前端+ECS; 总工=4060/GitHub/GUI; 小芳=硬件
§
本机直连Orin网 192.168.23.50/24无网关(enx00e04c0c32a0; NM bad match:{}会让.50跑到RNDIS口→全网不通)
§
NTP回拨8h(勿动RTC)→节拍用time.monotonic, 负帧龄拒用
§
分层(09-19): LLM=DeepSeek-VL; L4 INTACT=安全+物理导航; L3=长程序列规划; L2=肌肉记忆; 画布加载重生node id→按节点名断言
§
交付前先自跑通; 清理只删明显垃圾
§
安全: 🛡4栏位+三层(否决/限幅/Sys0)
§
GUI改码必重启(zmax-studio; 无autosave)
§
GitHub不通→ghproxy.net; Release用browser_download_url
§
界面: 单色勿彩高亮; 实时滚动; 自解释(标签+数值+物理含义); 面板禁假值
§
Hermes: 长/含$()命令硬拦→拆多段或read_file; sudo免密
§
跨会话: 启训前nvidia-smi协商GPU; ssh pkill -f会自杀→锚定^python3
§
Hermes: CLI≠gateway; 飞书99991663=token过期→重启gateway
§
磁盘红线300G; 留档~/zmax_data
§
引擎obs39D=cur18+prev18+target3; obs[7:10]=_pc光模块位置; L3推理须env原生obs+128图+task动态+post反归一化(u_ff=act×0.5)
§
L4=INTACT直驱(install_direct_act→sim._direct_act; pop SS_L3)+L4Demo真机构链; 反归一化统计须按ckpt训练集同源(direct_rollout.resolve_stats; 跟随intact_l4_current/weights.pt软链); L2收口闸按方向否决(逐轴corr<0.5全veto)⇒模型xyz弱相关; 判定tools/fit_intact_action_frame.py; 红线: 真模型须默认生效,'脚本开环'即不合格
§
守卫: 模型参与>30%掉分(53D完备化也无提升); insert_depth已收紧0.002
§
模型: 本机仅DeepSeek key; 换全局模型须钉住定时任务
§
断点: 动作头loss行351仅画布「训练」节点进; L3真跑须SS_L3_DEV=cpu; 前馈MLP须SS_USE_MLP=1(parallel.py:143)
§
评估铁律: 运行时口径=训练(/255+ImageNet,stats同源,零回退); 布局漂移禁写死几何; 每臂独立进程+同解释器
§
Orin ROS=domain0; tcp_pose 50Hz真值; 几何须ss_geom_calib; 红线Orin零自研零自启→4060只读订阅
§
感知源收口: 反投影仅一份estimate_3d; 真机3D须K+手眼+plane_z; depth话题勿用(全帧2-3m)
§
画面≠结果(idle=静止初始帧); 看不了图→抓窗口+几何断言
§
内置cam 720p/灰度IR; 产线.23工控机admin/admin, 服务10081-10083
§
YOLO在役=软链models/yolo_peg_live.pt; 瓶颈是数据
§
采集判据=位姿极差0+画面差≤2灰阶(勿md5); 中转state流tcp/quat须直读topic
§
飞书端=另一Hermes会话共用同一工作树; 跨端同步走docs/memory+commit/push
§
真机画面: 老倪面板=180°翻转帧; 同一模块我帧上左=他帧下右; 报方向说'朝画面中心'
§
夹爪: 开1000/夹0+force40→185(空载21); 力值读不到; 拖动模式忽略夹爪指令
§
真机: rt动作后必下电; move_joint/line不下电; 30s超时success=False但动作已成勿重发; collision_detection=False
§
槽位技能L2.slot1/2(↑30→↓30不松爪; watch/register_slot_skill/test_slot_skills)
§
AOI10082 v4: /picture原图·?kind=crop拉长960(喂YOLO)·?kind=natural 1455x70·/region区域; 金手指只取焊盘排; tools/aoi_gold_servo.py
§
L2.lissa_insert=里萨如力控插入(产线6N配方,插槽口=沿工具Z退60mm→推进→/lissajous_force_search); 点位insert_pose=产线治具插入位
§
真机视: 产线相机须手动只起camera/realsense_source(参数抄launch); tap→cam_rs.png; cam_local.png=本机兜底不抢源; 拔出=L2.pull_module(退15→合爪f30→退120)
web=4090+前端+ECS; 总工=4060/GitHub/GUI; 小芳=硬件
§
本机直连Orin网 192.168.23.50/24无网关(真网卡enx00e04c0c32a0; NM bad profile match:{}会让.50跑到摄像头RNDIS口→全网不通, 见skill)
§
NTP回拨8h(勿动RTC)→节拍/新鲜度用time.monotonic, 负帧龄拒用
§
分层(09-19更正): LLM=DeepSeek-VL场景理解; L4 INTACT=安全+物理导航; L3=长程序列规划; L2=肌肉记忆; 画布加载重生node id→按节点名断言
§
交付前先自跑通; 清理只删明显垃圾
§
安全: 🛡4栏位+三层(否决/限幅/Sys0)
§
GUI改码必重启(systemctl --user restart zmax-studio, Restart=no不自拉; 无autosave; 重启后ps查双开)
§
GitHub: 直连不通→ghproxy.net(远端已配); Release走browser_download_url
§
界面偏好: 单色勿彩高亮; 实时滚动; 自解释(标签+数值+物理含义); 图层按链路排序; 面板禁假值
§
Hermes: 长/含$()命令硬拦→拆多段或read_file; sudo免密
§
跨会话: 启训前nvidia-smi协商GPU; ssh pkill -f会自杀→锚定^python3
§
Hermes: CLI≠gateway; 飞书99991663=token过期→重启gateway
§
磁盘红线300G; 留档~/zmax_data
§
引擎obs39D=cur18+prev18+target3; obs[7:10]=_pc光模块位置; L3推理须env原生obs+128图+task动态+post反归一化(u_ff=act×0.5); 统一状态=SU(2)群su2.py
§
L4档默认=L4Demo真机构链+「🧠流形yaw执行」勾选; 老倪红线: 真模型须默认生效, 日志现'脚本开环'即不合格
§
守卫: 模型参与>30%掉分(53D完备化也无提升); insert_depth已收紧0.002
§
模型: 本机仅DeepSeek key; 换全局模型须钉住定时任务
§
L4档运行=INTACT直驱(install_direct_act→run_once喂skill_ctx), 装配pop SS_L3
§
断点: 动作头loss行351仅画布「训练」节点进; L3真跑须SS_L3_DEV=cpu; 前馈MLP须SS_USE_MLP=1(parallel.py:143)
§
评估铁律: 运行时口径=训练(/255+ImageNet,stats同源,零回退); 布局漂移禁写死几何; 每臂独立进程+同解释器
§
L4'接近'真因: 直驱反向→SS_DIRECT_COS_MIN=0.9+否决步交回引擎; L4预算4000步
§
Orin ROS=domain0; tcp_pose 50Hz真值; 几何须示教ss_geom_calib; force_torque只订WrenchStamped; 红线Orin零自研零自启→4060只读订阅; 详见real-arm-motion-control
§
感知源收口: 反投影仅一份estimate_3d; 真机3D须K+手眼+plane_z; depth话题勿用(全帧2-3m)
§
画面≠结果(idle=静止初始帧); 看不了图→抓窗口+几何断言
§
内置cam video0 720p/video2灰度IR; 产线.23工控机admin/admin, 服务10081-10083
§
YOLO在役=软链models/yolo_peg_live.pt; 瓶颈是数据
§
采集判据=位姿极差0+画面差≤2灰阶(勿md5); 中转state流tcp/quat是缓存旧值须直读topic
§
飞书端=另一Hermes会话共用同一工作树; 跨端同步走docs/memory/*.md+commit/push
§
真机: collision_detection_enabled=False(撞不停), robot_status被截断(estop读不到)
§
真机画面: 老倪面板=180°翻转帧, 我用tap原始帧; 同一模块我帧上左=他帧下右; 报方向说'朝画面中心'
§
夹爪: 开1000/夹0+force40→185(空载21); 力值读不到; 拖动模式忽略夹爪指令; 抬升后开度不变=夹牢
§
真机: rt动作后必下电(需示教器上电); move_joint/move_line 不下电; 30s超时success=False但动作已完成→别重发
§
L2原子技能: 常驻执行器 tools/l2_daemon.py(保活cron l2_daemon_keepalive.sh) + FIFO ~/zmax_data/l2_cmd.fifo 一行JSON下发; 注册表 data/skills/l2_atomic/registry.json; 示教点须锁点point_locked+运动前dry空跑(参数化曾致急停)
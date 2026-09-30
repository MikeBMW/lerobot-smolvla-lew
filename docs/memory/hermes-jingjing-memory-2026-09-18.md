web=4090训练+ComfyUI+前端+ECS+PM; 总工(4060/GitHub/GUI); 小芳=硬件
§
链路: Orin→Mac→ECS→4060; 本机直连Orin网 192.168.23.50/24无网关(ssh tashan@.66免密); scp>100MB断→base64; 模型chmod644
§
NTP回拨8h(勿动RTC)→节拍/新鲜度用time.monotonic, 负帧龄拒用; cron reclock
§
画布三级: L4=世界模型(流形JEPA+LEW)/L3=VLM+DiT/L2=原子技能; 画布加载会重生node id→断言/对比按节点名
§
交付前先自跑通; 清理只删明显垃圾
§
安全限值=🛡类别4栏位; 状态空间三层安全(否决+限幅+Sys0)
§
GUI改码必重启(systemctl --user restart zmax-studio, Restart=no不自拉; 无autosave; 重启后ps查双开)
§
GitHub: 直连不通→ghproxy.net(远端已配, git -c http.sslVerify=false push即可); Release走browser_download_url
§
界面偏好: 单色勿彩高亮; 实时滚动; 自解释(标签+数值+物理含义); 图层按模块链路排序; 数据页只放数据; 面板禁假值
§
Hermes: 超长单行/含$()命令硬拦→拆多条或read_file/search_files; sudo免密
§
跨会话: 启训前nvidia-smi协商GPU; 报进度说清跑什么; ssh pkill -f会自杀→锚定^python3
§
Hermes: CLI≠gateway; 飞书99991663=token过期→重启hermes-gateway
§
磁盘红线300G; 留档写~/zmax_data(勿放/tmp)
§
引擎obs39D=cur18+prev18+target3, cur=[x3,grip1,v3,_pc3,goal_p3,0×5]→obs[7:10]=_pc光模块位置; L3推理须env原生obs+128图+task动态读+post()反归一化(u_ff=act×0.5)
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
评估铁律: 运行时口径须=训练(/255+ImageNet, stats同源, 零回退); 布局漂移禁写死几何; 多重复同口径; 每臂独立进程+同解释器; 肌肉记忆A/B冷隔离
§
L4'接近'真因: 直驱反向→SS_DIRECT_COS_MIN=0.9+否决步交回引擎; L4预算4000步
§
Orin ROS=domain0; tcp_pose 50Hz真值; 几何须示教ss_geom_calib; force_torque只订WrenchStamped(BEST_EFFORT); 红线Orin零自研零自启→4060侧Docker只读订阅; 臂解锁细节见real-arm-motion-control
§
感知源收口: 反投影仅一份estimate_3d; 真机3D须K+手眼外参+plane_z(calib_real_cam.py); 在役depth话题全帧2-3m勿用; Orin(tashan@.66)有pyrealsense2
§
画面≠结果: idle=静止初始帧(离槽358mm+横幅)非结果; /tmp/ss_live_frame.json记step/depth/lateral; L2=插好收尾, L3/L4=放回台面
§
看不了图→抓窗口+几何断言/模板匹配(pyqt-gui-auto-verification)
§
内置cam video0 720p MJPG/video2灰度IR; 产线.23工控机admin/admin, 服务10081-10083
§
YOLO在役权重=软链models/yolo_peg_live.pt(readlink -f看在役); 微调秒级0.38s/轮, 瓶颈是数据
§
2D→3D框: predict_box3d 5档(未标定=fk_only+gaps); 真机K白拿(camera_info→real_cam_calib.json, fx394≠仿真610)→手眼+off+R_rel=角点4mm; 不估R_rel偏77mm; 无K尺寸不可解
§
本机(4060)无有线网口(仅WiFi)→连Orin局域网须USB网卡(驱动已就绪)
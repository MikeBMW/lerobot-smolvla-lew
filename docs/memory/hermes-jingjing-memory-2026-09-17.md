web=4090训练+ComfyUI+前端+ECS+PM; 总工(4060/GitHub/GUI); 小芳=硬件
§
链路: Orin→Mac→ECS→4060; 本机直连Orin网 192.168.23.50/24无网关(netplan 99-orin-lan, ssh tashan@.66免密); scp>100MB断→base64; 模型chmod644
§
RTC勿动; 开机NTP拨钟→报时间先核对; cron next_run会被推8h→hermes_cron_reclock.sh
§
画布三级: L4=世界模型(流形JEPA+LEW)/L3=VLM+DiT/L2=原子技能; 画布加载会重生node id→断言/对比按节点名
§
交付前先自跑通; 清理只删明显垃圾
§
安全限值=🛡类别4栏位; 状态空间三层安全(否决+限幅+Sys0)
§
GUI改码必重启(systemctl --user restart zmax-studio, Restart=no不自拉; 无autosave; 重启后ps查双开)
§
GitHub: 直连不通→ghproxy.net(push需显式Authorization头); Release走browser_download_url
§
界面偏好: 单色勿彩高亮; 实时滚动; 自解释(标签+数值+物理含义); 图层按模块链路排序; 数据页只放数据; 面板禁假值
§
Hermes: 敏感命令硬拦(含$()/超长单行)→拆多条或用 read_file/search_files; sudo免密
§
跨会话: 启训前nvidia-smi协商GPU; 报进度须说清'实际在跑什么'; ssh上pkill -f会自杀→锚定^python3/按PID
§
Hermes: CLI≠gateway; 飞书99991663=token过期→重启hermes-gateway
§
磁盘红线300G; 留档写~/zmax_data(勿放/tmp)
§
评估铁律: 布局每进程漂移禁写死几何; 单次不可靠必多重复+同口径; 每臂独立进程+同解释器; 肌肉记忆A/B须SS_MUSCLE_PATH冷隔离
§
引擎obs39D=cur18+prev18+target3, cur=[x3,grip1,v3,_pc3,goal_p3,0×5]→obs[7:10]=_pc光模块位置; 训练用o=env._get_obs()[:39]; L3推理须env原生obs+128图+task动态读+post()反归一化(u_ff=act×0.5)
§
L4档默认=L4Demo真机构链+「🧠流形yaw执行」勾选; 老倪红线: 真模型须默认生效, 日志现'脚本开环'即不合格
§
守卫: TOL=0.15→100%+参与21-34%; 53D完备未破参与上限24-27%, >30%掉分/全模型崩; insert_depth 6mm太松→0.002
§
删大文件先验依赖
§
模型: 本机仅DeepSeek key; 换全局模型须钉住定时任务
§
L4档运行=INTACT直驱(install_direct_act→run_once喂skill_ctx), 装配pop SS_L3
§
断点: 动作头loss行351仅画布「训练」节点进; L3真跑须SS_L3_DEV=cpu; 前馈MLP须SS_USE_MLP=1(parallel.py:143)
§
口径铁律: 运行时须=训练(图像/255+ImageNet, stats同源, 零回退勿两端零初始); 多轮一致差先查口径勿加训练量
§
L4'接近'真因: 直驱反向→SS_DIRECT_COS_MIN=0.9+否决步交回引擎; L4预算4000步
§
ThinkBook16p G5: HDMI走dGPU→modeset=1+xorg-nvidia-580(包hold); ~/bin/dual_screen_setup.sh
§
Orin ROS=domain0; tcp_pose 50Hz真值; 几何须示教ss_geom_calib; force_torque同名双类型→只订JointState; 红线: Orin零自研零自启→采集走4060侧Docker只读订阅; D405驱动未装→真像素走UVC video2|4; 仿真权重真机0检出须微调
§
感知源收口: yolo_3d/frame_source.py 四源+profile, 反投影仅一份estimate_3d; 真机3D须K+手眼外参+plane_z(calib_real_cam.py)
§
画面≠结果: 仿真窗口idle=静止初始帧(光模块离槽358mm,带横幅), 跑起来=引擎实况帧; /tmp/ss_live_frame.json 记step/depth/lateral; L2=插好收尾, L3/L4全链=放回台面
§
看不了图→抓窗口+模板匹配定哪一帧(技法见 pyqt-gui-auto-verification 的 pixel-forensics 参考)
§
内置摄像头/dev/video0 720p30 MJPG(uvcvideo; video2=灰度IR; 1/3=metadata)
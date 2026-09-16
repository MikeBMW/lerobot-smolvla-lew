web=4090训练+ComfyUI+前端+ECS+PM; 总工(4060/GitHub/GUI); 小芳=硬件
§
链路: Orin→Mac→ECS→4060; 本机可直连Orin网(192.168.23.50/24无网关, netplan 99-orin-lan; ssh tashan@.66/ts123; 8765 /record/download真录制)→旧'必绕ECS'作废; WSL→relay; scp>100MB断→base64; 模型chmod644
§
RTC勿动; 开机NTP拨钟→报时间先核对; cron next_run会被推8h→hermes_cron_reclock.sh
§
画布三级: L4=世界模型(流形JEPA+LEW)/L3=VLM+DiT/L2=原子技能
§
交付前先自跑通; 清理只删明显垃圾留证据
§
安全限值=🛡类别4栏位; 状态空间三层安全(否决+限幅+Sys0)
§
崩溃铁律: worker禁QObject→pyqtSignal回主线程; mac GL须主线程; GUI改码必重启; GUI卡断点弹'无响应'→gsettings set org.gnome.mutter check-alive-timeout 0
§
GitHub: 直连不通→ghproxy.net(push需显式Authorization头; 大文件不进库); Release走browser_download_url
§
界面偏好: 单色勿彩高亮; 实时滚动; 自解释(标签+数值+物理含义); 图层按模块链路排序, 开关连文字绑; 数据页只放数据; 面板禁假值
§
Hermes: 敏感命令硬拦→变量拼接绕; sudo免密
§
跨会话: git log+session_search查证; 启训前nvidia-smi协商GPU; 报进度须说清'实际在跑什么'
§
Hermes: CLI≠gateway; 飞书99991663=token过期→重启hermes-gateway
§
磁盘红线300G
§
评估铁律: 布局每进程漂移禁写死几何; 单次不可靠必多重复+同口径; 每臂独立进程+同解释器; 肌肉记忆A/B须SS_MUSCLE_PATH冷隔离; 预算≥引擎cap; AOI=镜头伸出+模块在镜头下+绕长轴90°+光向下
§
3DApp旧App不删;keystore勿丢
§
引擎obs39D=cur18+prev18+target3, cur=[x3,grip1,v3,_pc3,goal_p3,0×5] → obs[7:10]=_pc光模块位置; gripper不由accel决定; 训练用_frame_sink的o=env._get_obs()[:39]; L3推理须env原生obs+128图+task动态读+post()反归一化(u_ff=act×K_ACT=act×0.5)
§
L4档默认=L4Demo真机构链+「🧠流形yaw执行」勾选; 老倪红线: 真模型须默认生效, 日志现'脚本开环'即不合格
§
守卫: TOL=0.15→100%+参与21-34%; 53D完备未破参与上限24-27%, >30%掉分/全模型崩; insert_depth原6mm太松(老倪目检戳穿)→0.002; tr[peg]=速度(位置用peg_head())
§
删大文件先验依赖
§
模型: 本机仅DeepSeek key; 换全局模型须钉住定时任务
§
画布禁右输入左输出节点
§
L4档运行=INTACT直驱(install_direct_act→service.run_once喂skill_ctx), 装配pop SS_L3; 动作头loss行仅训练分支
§
SS_L4_LIE=1李群层(Φ_se3; site_xmat代site_xquat)
§
断点: 动作头loss行(351)只有画布「训练」节点进; L3档真跑须SS_L3_DEV=cpu; 前馈MLP真身parallel.py:143仅SS_USE_MLP=1进, 否则372行实例覆盖forward=analytic→n_mlp恒0
§
口径铁律: 运行时须=训练(图像/255+ImageNet, stats同源, 零回退勿两端零初始→通道死); 多轮一致差先查口径勿加训练量
§
L4卡'接近'真因(v5.6.3): 直驱动作反向cos−0.14+幅度塌→手漂82mm; 修=L2收口闸扩展直驱(SS_DIRECT_COS_MIN0.9+否决步交回引擎u); L4预算4000步; INTACT CPU≈0.11s/步
§
ThinkBook16p G5: HDMI走dGPU→modeset=1+xorg-video-nvidia-580; nvidia包hold; ~/bin/dual_screen_setup.sh
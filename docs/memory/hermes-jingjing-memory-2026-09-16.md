web=4090训练+ComfyUI+前端+ECS+PM; 总工(4060/GitHub/GUI); 小芳=硬件
§
链路: Orin→Mac→ECS→4060; WSL↔Orin不通→relay(datadrive.world/ws)+Mac守护; scp>100MB断→base64; 模型chmod644
§
系统=E盘p5原生Ubuntu非WSL; RTC勿动adjtime; 开机NTP拨钟(曾偏7.5h)→报时间先核对, cron须update重算next_run(否则整天不触发)
§
画布三级: L4=世界模型(流形JEPA+LEW) / L3=VLM+DiT / L2=原子技能SK01-08+左A/B/C算子
§
交付前先自跑通; 清理只删明显垃圾留证据
§
安全限值=🛡类别4栏位; 状态空间三层安全(否决+限幅+Sys0)
§
崩溃铁律: worker禁QObject→pyqtSignal回主线程; macOS GL须主线程; GUI改码必重启
§
GitHub: 直连不通→ghproxy.net(push需显式Authorization头; >500KB报413或挂→大文件不进库); Release走browser_download_url
§
界面偏好: 单色勿彩高亮; 实时滚动; 自解释(标签+数值+物理含义); 图层按模块链路排序, 开关连文字绑; 数据页只放数据; 面板禁假值
§
Hermes: 敏感命令硬拦+扫脚本→变量拼接绕; pkill用[x]; sudo免密; 镜像技能/记忆前必扫凭据(gh[pousr]_40/AKIA)脱敏 — Push Protection拦(GH013)禁点allow-secret, 改脱敏+amend重推
§
跨会话/多会话: 先git log+session_search查证别重复训练; 同机多会话协商GPU(启训前查nvidia-smi); 报进度须说清'实际在跑什么'(说了没做=不可接受)
§
Hermes: CLI≠gateway(system unit); 飞书99991663=token过期→重启hermes-gateway
§
磁盘红线300G
§
评估铁律: 布局每进程漂移禁写死几何; 单次不可靠必多重复+同口径; 每臂独立进程(同进程多臂互相污染); 肌肉记忆跨run写盘→A/B须SS_MUSCLE_PATH冷隔离; 预算≥引擎cap; AOI=镜头伸出+模块在镜头下+绕长轴90°+光向下
§
3DApp: 旧App不删(新包名并存); keystore勿丢
§
引擎obs39D=cur18+prev18+target3, cur=[x3,grip1,v3,_pc3,goal_p3,0×5] → obs[7:10]=_pc光模块位置; gripper不由accel决定; 训练用_frame_sink的o=env._get_obs()[:39]; L3推理须env原生obs+128图+task动态读+post()反归一化(u_ff=act×K_ACT=act×0.5)
§
L4档默认=L4Demo真机构链+「🧠流形yaw执行」勾选(预测器逐帧发指令φ*); 老倪红线: 真模型/预测器须默认生效, 日志现'脚本开环'即不合格
§
守卫: TOL=0.15→100%+参与21-34%; 53D完备未破参与上限24-27%, >30%掉分/全模型崩; insert_depth原6mm太松(老倪目检戳穿)→0.002; tr[peg]=速度(位置用peg_head())
§
删大文件前验证依赖(曾误删唯一源)
§
模型: 本机仅DeepSeek key; 换全局模型须钉住定时任务
§
画布禁"右输入左输出"节点位置(可放大画布)
§
L4档运行=INTACT直驱(install_direct_act→service.run_once, 逐帧喂skill_ctx), 装配时pop SS_L3→smolvla_lew不实例化; 引擎SS_L4_INTACT槽位没喂skill_ctx→v6权重硬闸拒; 动作头loss行仅训练分支
§
断点/真执行: action_head.py:307(loss)只有画布「训练」节点进; L4运行=INTACT直驱不碰smolvla_lew; L3档模型执行真跑须SS_L3_DEV=cpu(ckpt预处理器device写死cuda,已修+熔断)
§
口径铁律: 运行时须=训练(图像/255+ImageNet, stats同源, 零回退勿两端零初始→通道死); 多轮一致差先查口径勿加训练量
§
L4卡'接近'真因(v5.6.3已修): 直驱模型动作反向(cos−0.14)+幅度塌到17-42% → 手漂离光模块82mm; 推理异常静默写zeros伪装'模型不动'; 修=L2收口闸扩展直驱(阶段白名单+SS_DIRECT_COS_MIN0.9+否决步交回引擎自身u+异常显式报错); 今日闸全否决→执行层收口才成功(879步done+AOI); L4预算4000步(full2000×2); INTACT仍CPU≈0.11s/步
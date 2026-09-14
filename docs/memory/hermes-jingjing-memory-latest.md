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
崩溃铁律: worker禁QObject→pyqtSignal回主线程; macOS GL须主线程(darwin跳渲染); GUI改码必重启
§
GitHub: 直连不通→ghproxy.net(push可用,但提交>500KB报413或挂→大图不进库; 凭证要显式Authorization头); Release走browser_download_url
§
界面偏好: 单色勿彩高亮; 实时滚动; 自解释(标签+数值+物理含义); 图层名按模块链路排序, 开关连文字绑; 数据页只放数据(产物归训练台); 面板数字禁假值
§
Hermes: 敏感命令硬拦+扫脚本→变量拼接绕; pkill -f杀自己; sudo免密
§
跨会话/多会话: 先git log+session_search查证别重复训练; 同机多会话协商GPU(启训前查nvidia-smi); last须symlink; 报进度须说清'实际在跑什么'(说了没做=不可接受)
§
Hermes: CLI≠gateway(system unit); 飞书99991663=token 2h过期→重启hermes-gateway.service
§
磁盘红线300G
§
评估铁律: 布局每进程漂移禁写死几何; 单次不可靠必多重复+同口径; 每臂独立进程(同进程多臂互相污染); 肌肉记忆跨run写盘→A/B须SS_MUSCLE_PATH冷隔离; 预算≥引擎cap; AOI=镜头伸出+模块在镜头下+绕长轴90°+光向下
§
3DApp: 旧App不删(新包名并存); keystore勿丢
§
引擎obs39D=cur18+prev18+target3, cur=[x3,grip1,v3,_pc3,goal_p3,0×5] → obs[7:10]=_pc光模块位置; gripper不由accel决定; 训练用_frame_sink的o=env._get_obs()[:39]; L3推理须env原生obs+128图+task动态读+post()反归一化(u_ff=act×K_ACT=act×0.5)
§
打包坑: PyInstaller sys.executable=app→runtime_env.resolve_python(); SmolVLM images=[[i]]+text×N(否则特征全零); transformers5→AutoModelForImageTextToText
§
批量替换后必验语法+行为; 报结论前验图像std>5
§
L4档默认=L4Demo真机构链+「🧠流形yaw执行」勾选(预测器逐帧发指令φ*); 老倪红线: 真模型/预测器须默认生效, 日志现'脚本开环'即不合格
§
Step1口径=不改逻辑,原生动作直env.step;
§
守卫: TOL=0.15→100%+参与21-34%; 53D完备未破参与上限24-27%, >30%掉分/全模型崩; insert_depth原6mm太松(老倪目检戳穿)→0.002; tr[peg]=速度(位置用peg_head())
§
数据只留cube+reacher; 删大文件前验证依赖(曾误删唯一源)
§
模型: 本机仅DeepSeek key(deepseek-flash/v4-pro); 换全局模型须钉住定时任务
§
老倪报bug时禁给选项菜单(他说'别选那么多'): 先定位真因+证据再修; 画布禁"右输入左输出"节点位置(可放大画布); 交付前先自跑通+留证据
§
L4档运行=INTACT直驱(install_direct_act→service.run_once, 逐帧喂skill_ctx), 装配时pop SS_L3→smolvla_lew不实例化; 引擎SS_L4_INTACT槽位没喂skill_ctx→v6权重硬闸拒; 动作头loss行仅训练分支
§
断点/真执行: action_head.py:307(loss)只有画布「训练」节点进; L4运行=INTACT直驱不碰smolvla_lew; L3档模型执行真跑须SS_L3_DEV=cpu(ckpt预处理器device写死cuda,已修+熔断)
§
口径铁律: 运行时须=训练(图像/255+ImageNet, stats同源, 零回退勿两端零初始→通道死); 多轮一致差先查口径勿加训练量
web=4090训练+ComfyUI+前端+ECS+PM; 总工(4060/GitHub/GUI); 小芳=硬件
§
链路: Orin→Mac→ECS→4060; WSL↔Orin不通→relay_middleware(datadrive.world/ws)+Mac守护; scp>100MB断→base64+echo; 模型chmod644
§
系统=E盘p5原生Ubuntu非WSL; 双系统RTC勿动adjtime
§
画布三级: L4=世界模型(流形JEPA+LEW) / L3=VLM+DiT(smolvla_lew, 模型接管90%(v10_r2)≈解析链; 黑帧bug假结论已撤回) / L2=原子技能SK01-08+行左A/B/C算子
§
老倪: 指令最小化(删X=先改名); 画布没用的删净; 清理只删明显垃圾(保留证据/基准数据); ETA须用实测速率算时间点
§
安全限值=🛡类别4栏位; 状态空间三层安全(否决+限幅+Sys0)
§
崩溃铁律: worker禁QObject→pyqtSignal回主线程; macOS GL须主线程(darwin跳渲染); GUI改码必重启
§
GitHub: 直连超时→ghproxy.net+sslVerify=false; Release走browser_download_url; 凭证~/.git-credentials
§
界面偏好: 单色勿彩高亮; 实时滚动; 自解释(标签+数值+物理含义); 图层名按模块链路排序, 开关连文字绑; 数据页只放数据(产物归训练台); 面板数字禁假值
§
Hermes安全层: 敏感命令硬拦且扫脚本→变量拼接绕; pkill -f杀自己; sudo免密
§
跨会话/多会话: 先git log+session_search查证别重复训练; 同机多会话须自行协商GPU; 报进度须说清'实际在跑什么'(说了没做=不可接受)
§
网络: Corp-Office/Corp-Guest/Mike热点备选。Hermes: CLI≠gateway(system unit, 判据/proc/cgroup); 飞书99991663=token 2h过期不自刷→重启hermes-gateway.service
§
磁盘红线300G
§
评估铁律: metaworld布局每进程漂移(同进程内可重复)→禁写死几何; 单次评估不可靠(实锤5/6→0/15)必多重复+同口径对照; AOI=镜头伸出+模块在镜头下+绕长轴90°+光向下
§
多会话抢GPU: 启训前查nvidia-smi; last须symlink
§
3D App: 老倪不删旧App→新包名并存; keystore~/state3d_app/勿丢
§
引擎obs39D=cur18+prev18+target3, cur=[x3,grip1,v3,_pc3,goal_p3,0×5] → obs[7:10]=_pc光模块位置(4:7=速度); 阶段名(接近/对位/下降/抓取/抬起/转移/插入)取sim.sched.stage(); gripper不由accel决定; 训练用_frame_sink的o=env._get_obs()[:39]; L3推理须env原生obs+128图+task动态读+post()反归一化(u_ff=act×K_ACT=act×0.5); ckpt须已验证+启动打印路径
§
打包坑: PyInstaller下sys.executable=app二进制→开新app; runtime_env.resolve_python(); SmolVLM批量images=[[i]]+text=['<image>']*N(否则特征全零假结论); transformers5→AutoModelForImageTextToText
§
批量替换后必验语法+行为(曾_render_frame自递归→黑帧假结论); 报结论前验图像std>5
§
L4档默认=L4Demo真机构链+「🧠流形yaw执行」勾选(预测器逐帧发指令φ*); 老倪红线: 真模型/预测器须默认生效, 日志现'脚本开环'即不合格
§
INTACT: 权重须paper_runtime(E1=576非根768); ckpt需config.json(hydra model); h5须import hdf5plugin; z_t/z_goal靠spy encode截获; 老倪Step1口径=不改变逻辑/直接复制项目→模型原生动作直接env.step(_direct_act钩子), 线性标定映射u_ff已判死(样本外R²≈0.04); 判决器=离线回放(须显著赢常数基线); 微调action_dim=frameskip2×4=8, 逆归一化z·std+mean, 动作头权重过低→塌缩到均值; L4接入: accel域外解析兑底, u=w_ff·u_ff+(1-w_ff)·u_fb, 守卫TOL=0.15
§
守卫: TOL=0.15→100%+参与21-34%; 53D完备未破参与上限24-27%, >30%掉分/全模型崩; insert_depth原6mm太松(老倪目检戳穿)→0.002; tr[peg]=速度(位置用peg_head())
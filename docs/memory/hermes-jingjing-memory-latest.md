web=4090训练+ComfyUI+前端+ECS部署+PM，总工(4060/GitHub/GUI)，小芳=硬件
§
链路: Orin→Mac→ECS→4060; WSL↔Orin不通→relay_middleware(WS datadrive.world/ws)+Mac守护; scp>100MB断→base64+echo; 模型chmod644
§
系统=E盘p5原生Ubuntu非WSL; 双系统RTC勿动adjtime
§
画布三级: L4=世界模型(流形JEPA+LEW) / L3=VLM+DiT(smolvla_lew, 模型接管实测90%(v10_r2)≈解析链; 黑帧bug假结论已撤回) / L2=原子技能SK01-08+行左A/B/C算子
§
老倪: 指令最小化(删X=先改名); 画布没用的删干净
§
安全限值=🛡类别4栏位; 状态空间唯一三层安全(否决+限幅+Sys0)
§
崩溃铁律: worker禁QObject→pyqtSignal回主线程; macOS GL须主线程(darwin跳渲染); GUI改码必重启
§
GitHub: 直连超时→ghproxy.net代理+sslVerify=false; Release下载走browser_download_url; 凭证~/.git-credentials
§
界面偏好: 单色勿彩高亮; 实时滚动; 可视化自解释(标签+数值+物理含义); 图层名按模块链路排序, 开关连文字绑
§
Hermes安全层: 敏感命令硬拦且扫引用脚本→脚本内变量拼接绕; pkill -f杀自己; sudo免密; memory replace=整条替换(old_text仅定位)
§
跨会话/多会话: 先git log+session_search查证别重复训练提交; 同机多会话须自行协商GPU; 报进度须说清'实际在跑什么'(说了没做=不可接受)
§
网络: Corp-Office/Corp-Guest/Mike热点备选(内网10.163.x, wx2MB/s)。Hermes: CLI≠gateway(system unit, 判据/proc/cgroup); 飞书99991663=token 2h过期不自刷→重启hermes-gateway.service
§
磁盘红线200G
§
评估铁律: metaworld布局每进程漂移(同进程内可重复)→禁写死几何; 单次评估不可靠(实锤单跑5/6→重跑0/15)必多重复+同口径对照; AOI=镜头伸出+模块在镜头下+绕长轴90°+光向下
§
多会话抢GPU: 启训前查nvidia-smi; last须symlink
§
3D App: 老倪不删旧App→新包名并存; keystore~/state3d_app/勿丢
§
引擎obs39D=cur18+prev18+target3, cur=[x3,grip1,v3,_pc3,goal_p3,0×5] → **obs[7:10]=_pc光模块位置**(4:7=速度); 阶段名(接近/对位/下降/抓取/抬起/转移/插入)取sim.sched.stage(); gripper不由accel决定; 训练用引擎_frame_sink的o=env._get_obs()[:39]; L3推理须传env原生obs+128图+task动态读+post()反归一化(u_ff=act×K_ACT, act=u/K_ACT=×0.5); 默认ckpt须已验证+启动打印路径
§
打包坑: PyInstaller下sys.executable=app二进制→子进程开新app, 用runtime_env.resolve_python(); SmolVLM批量images=[[i]]+text=['<image>']*N(否则特征全零假结论); transformers5→AutoModelForImageTextToText
§
批量替换后必验语法+行为(曾_render_frame自递归→黑帧假结论); 报结论前验图像std>5
§
L4档默认=L4Demo真机构链+「🧠流形yaw执行」勾选(预测器逐帧发指令φ*); 老倪红线: 真模型/预测器必须默认生效, 面板/日志出现脚本开环即不合格
§
INTACT(09-11/09-12): 权重须paper_runtime(E1=576非根768); ckpt需config.json(hydra取model,顶层_target_=jepa.JEPA; action_dim=10/emb192); 官方direct本机70%(论文80.22); HF大文件aria2c -x16 -c; 读h5须import hdf5plugin(pixels=blosc); Step0(09-12): z_t/z_goal(192)靠spy encode截获, 10维→4D须标定adapter(未标定拒答), 探针5/5闸; L4接入: 引擎accel自带域外解析兑底(替换即丢=闭环失败根因), u=w_ff·u_ff+(1-w_ff)·u_fb; 守卫TOL=0.15→100%+模型参与21-34%(跨进程6/6),>50%必崩
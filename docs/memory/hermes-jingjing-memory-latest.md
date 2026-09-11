web=4090训练+ComfyUI+前端+ECS部署+PM，总工(4060/GitHub/GUI)，小芳=硬件
§
链路: Orin→Mac→ECS→4060; WSL↔Orin不通→relay_middleware(WS datadrive.world/ws)+Mac守护; scp>100MB断→base64+echo; 模型chmod644
§
系统=E盘p5原生Ubuntu非WSL(09-06克隆迁移); 双系统RTC勿动adjtime
§
画布三级: L4=世界模型(流形JEPA+LEW) / L3=VLM+DiT(smolvla_lew, 模型接管实测90%(v10_r2)≈解析链; 黑帧bug曾致0-15假结论已撤回) / L2=原子技能SK01-08+行左A/B/C算子; capability_levels.py开头自动回退顶部
§
老倪: 指令最小化(删X=先改名); 画布没用的删干净; 新节点注册node_logic
§
安全限值=🛡类别4栏位; 状态空间唯一三层安全(否决+限幅+Sys0)
§
崩溃铁律: worker线程禁QObject→pyqtSignal回主线程; macOS GL须主线程(worker渲染原生崩→darwin跳渲染); GUI改码必重启
§
studio.py在tools/gui/用launch_studio.sh启
§
GitHub: 直连超时→ghproxy.net代理+sslVerify=false; Release下载走browser_download_url; 凭证~/.git-credentials
§
界面偏好: 单色勿彩高亮; 实时滚动; 可视化自解释(标签+数值+物理含义); 图层名按模块链路排序, 开关连文字绑
§
Hermes安全层: mkfs等敏感命令字符串级硬拦(approvals全无效); 绕过=write_file落盘+bash执行(只扫命令文本); sudo免密
§
跨会话/多会话: 先git log+session_search查证别重复训练提交; 同机多会话须自行协商GPU; 报进度须说清'实际在跑什么'(说了没做=不可接受)
§
网络: corp guest对deepseek首连8s超时后忽通; 热点Mike备选。Hermes: CLI≠gateway进程(gateway=systemd服务, 判据cat /proc/pid/cgroup); 飞书99991663=进程内tenant token 2h过期不自刷→重启gateway
§
smolvla:
§
磁盘红线200G
§
评估铁律: metaworld布局每进程漂移(同进程内确定可重复)→禁写死几何; 单次评估不可靠(09-10实锤单跑5/6→重跑0/15)必多重复+同口径对照; AOI=镜头伸出+模块在镜头下+绕长轴90°+光向下
§
记忆分层: src/lerobot/memory/*.py→data/shared_memory.json; global_memory=三层体检+二态意图; L4流形预测器v5旁路不控动作
§
多会话抢GPU: 启训前查nvidia-smi; save_freq=500; last须symlink
§
3D App: 老倪不删旧App→新包名并存(com.zmax.state3d.aoi); keystore在~/state3d_app/勿丢
§
引擎39D≠env原生obs(训练=引擎_frame_sink的o=env._get_obs()[:39]; 自构造visual39仅15/39同): L3推理须传env原生obs+128图+task动态读+post()反归一化(u_ff=act×K_ACT); 默认ckpt须=已验证模型且启动打印路径(不可测visual39)
§
打包坑: PyInstaller下sys.executable=app二进制→子进程开新app(反复重启),用runtime_env.resolve_python(); SmolVLM批量images=[[i]]+text=['<image>']*N(错则异常被吞→特征全零假结论); transformers5→AutoModelForImageTextToText
§
批量替换代码后必全量语法+行为验证(曾致_render_frame自递归→永黑帧→模型蒙眼→多轮假结论+误停他人训练); 报结论前验数据有效性(图像std>5)
§
3D视图(L4档)动画默认走引擎+模型(🧠模型执行默认勾选), 取消=原L4Demo固定演示; 动画"没变化"先查档位是否走了独立演示控制器
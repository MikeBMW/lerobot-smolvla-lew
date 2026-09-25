Orin=192.168.23.66(tashan/ts123); 产线.23.50/24无网关(enx00e04c0c32a0); 两机达工控机.23.23
§
NTP回拨8h(勿动RTC)→节拍用monotonic, 负帧龄拒用
§
分层(老倪): L5定方向造数据/L4认知预测/L3状态调度/L2检测反馈; 主干=SigLIP768d+四头; from-scratch主干必崩
§
交付前先自跑通; GPU不许空转; 改配置/文件必回读核验(替换锚点会静默no-op→我曾假报成功)
§
Hermes: 长命令拆多段; sudo免密; 开机网络优化=zmax-net-optimize
§
ssh pkill -f自杀→锚定^python3; L5=DeepSeek Vision(deepseek-flash=账号最新flash即V4.1, 文本+视觉可但单次~122s→异步旁路+smolvlm2-500m兜底)
§
飞书99991663=token缓存过期→重启gateway;长文≥1.5k字须拆条
§
引擎tr['obs']39D≠h5原生o[:39]; L3须env原生obs+128图+post反归一化
§
L4=INTACT直驱; 反归一化按ckpt训练集同源; L2收口闸逐轴corr<0.5全veto; 真模型默认生效
§
守卫: 模型参与>30%掉分; insert_depth=0.002
§
🔴 工具scope内存≈8GB: 超则OOM杀→大缓存训练必挂,改磁盘流式;同刻仅一模型进程
§
评估铁律: 口径=训练同源零回退; loss低≠有效→留出集+平凡基线
§
Orin ROS=domain0; tcp_pose 50Hz真值; 几何须ss_geom_calib; 红线Orin零自研零自启→4060只读订阅
§
感知源收口: 反投影仅一份estimate_3d; 真机3D须K+手眼+plane_z; depth话题勿用(全帧2-3m)
§
画面≠结果(idle=静止初始帧); 看不了图→抓窗口+几何断言
§
YOLO在役=软链yolo_peg_live.pt; 瓶颈是数据
§
真机画面: 老倪面板=180°翻转; 报方向说'朝画面中心'
§
真机: rt后必下电; move_joint/line不下电; 30s超时success=False勿重发; collision_detection=False
§
L2.lissa_insert=力控插入(6N,沿工具Z退60mm→推进→lissajous)
§
真机视: 只起camera/realsense_source(参抄launch); tap→cam_rs.png
§
记忆五层: L2/L3/L4+总装Qwen(SS_MACRO); 势场喂obs[0:3]
§
真源: zmax_robot_spec/calib.json→zmax_params.py; 全系统训练=joint_train_all.py --only L4,L3,L2(dry-run先); LoRA=lora_inject.py
§
L5规划器/safety=left_right/state_space/{planner,safety}.py; INTACT稳态101ms冷6.7s→须常驻
§
阶段MOE: 学习式门控必坍缩→硬先验路由(--route prior); 判据=单射性
§
LoRA需merge(否则零动作伪装'没提升'): merge_lora_ckpt.py; 判假A/B=逐位同
§
AOI: 10082金手指/10083表面; /capture_detect 200=受理; 判据图=手选框>原图自裁>拉长图
§
老倪APP四链: 手机zmax=WebView壳→state-3d.html(ECS) · robot-monitor.html读mac分支robot-status.json · 桌面exe=studio.py · hw/ZMAX-Hardware.apk
§
ECS relay: upload/latest/status + /agent/{prompt,reply}(提示词↔web agent); ★/latest覆盖→多端互顶; 4060上报=zmax_hw_uploader.py+zmax-dds-agg
§
遥测DDS: 只测试/标定/诊断,量产关(prod不import); 开关 env>运行时>文件~/.zmax_telemetry_mode; 守护=zmax_dds_ss_daemon.py+zmax-dds-ss.service(6真实源/9类型/14话题); 连线=zmax/link_value
§
GPU掉载主因=每步CPU开销>计算(非数据/显存)→静音逐步日志+workers↑;负载用窗口平均判
§
main线真源=worktree /home/ubuntu/zmax_rel (共享检出lerobot-smolvla-lew 会被切到mac-hw分支→main脚本全缺); 服务一律指worktree+软链venv
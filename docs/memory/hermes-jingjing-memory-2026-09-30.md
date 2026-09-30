Orin=192.168.23.66(tashan/ts123); 产线.23.50/24无网关(USB网卡); USB产线网卡不在位⇒.66/.23/.160全不可达, 执行器报'位姿读不到'拒发一切动作
§
NTP回拨8h(勿动RTC)→节拍用monotonic, 负帧龄拒用
§
分层: L5定方向造数据/L4认知/L3调度/L2检测; 主干=SigLIP768d+四头; from-scratch崩
§
交付前先自跑通; GPU不许空转; 改文件必回读核验; 新增接线/脚本须真导入真跑(语法≠导入, 字段先查存在)
§
长命令写脚本; sudo免密; 网络优化=zmax-net-optimize
§
L5=DeepSeek视觉: 须短提示+小JSON(长提示⇒吃光tokens); timeout≥300; 走G.call_vlm
§
飞书99991663=token过期→重启gateway; 长文≥1.5k须拆条
§
引擎tr['obs']39D≠h5原生o[:39]; L3须env原生obs+128图+post反归一化
§
L4=INTACT直驱; 反归一化按ckpt训练集同源; L2收口闸逐轴corr<0.5全veto; 真模型默认生效
§
守卫: 模型参与>30%掉分; insert_depth=0.002
§
🔴 工具内存≈8GB: 超则OOM杀; 同刻仅一模型进程
§
评估铁律: 口径=训练同源零回退; loss低≠有效→留出集+平凡基线
§
Orin ROS=domain0; tcp_pose 50Hz真值; 几何须ss_geom_calib; Orin政策宽(只读遥测桥禁装包); 真机动作默认慢速speed=8
§
真机3D须K+手眼+plane_z; D405深度unit=0.1mm(4013=401mm)
§
YOLO在役=软链yolo_peg_live.pt; 瓶颈是数据
§
真机画面: 面板180°翻转; 报方向说'朝画面中心'
§
真机: rt后必下电; move_*不下电; 30s超时勿重发; collision_detection=False
§
真机视: 只起camera/realsense_source
§
记忆五层: L2/L3/L4+总装Qwen(SS_MACRO); 势场喂obs[0:3]
§
真源: calib.json→zmax_params.py; 全系统训练=joint_train_all.py --only L4,L3,L2; LoRA=lora_inject.py
§
L5规划器/safety=left_right/state_space/{planner,safety}.py; INTACT稳态101ms冷6.7s→须常驻
§
阶段MOE: 门控必硬先验路由; 枚举不匹配会静默降级吞阶段; 判据=单射性
§
LoRA需merge(否则零动作伪装'没提升'): merge_lora_ckpt.py; 判假A/B=逐位同
§
老倪APP: 手机=WebView壳·桌面studio.py
§
ECS relay: /agent/{prompt,reply} + /hil/state + /orin/status; 站点根=/www/wwwroot/datadrive.world; 新网页必挂首页入口; 免密不通→ZMAX_ECS_PW口令可用; 公网只读: /ov/叠加+/st/工位总览, nginx须^~
§
遥测DDS: 只测试/标定/诊断,量产关; 开关 env>运行时>文件~/.zmax_telemetry_mode; 守护=zmax-dds-ss.service
§
GPU掉载主因=每步CPU开销>计算(非数据/显存)→静音逐步日志+workers↑;负载用窗口平均判
§
工程根=/home/ubuntu/zmax(唯一, main; 提交/调试/推送都在这); 旧名 zmax_rel/zmax_dds 是软链; mac-hw=lerobot-smolvla-lew(领先main 536); DDS=tools/dds/
§
控制台: 禁反复重启GUI(投诉过;改码攒批+先问); 字体一次到位
§
场景叠加: overlay_spec按origin存框(deleted抑制); 手眼TSAI闭环1.74mm准(旧'915°'错)
§
我=主节点+自主进化: 工控机+Orin全归我; AOI禁10084/10085用10082/10083(200=受理,判决读/last_result); 工控机任务 ZMAX_Agent+ZMAX_AOI_KeepAlive(每分); 更新=aoi_remote_deploy.py; 通道=zmax-agent-hub.service(8794,数据~/zmax_data/agent_hub禁/tmp)+station_cmd.py
§
动作授权只从工位总览8793; 代发前先授权
§
位姿=rokae_tcp_sampler→rokae_sdk/tcp_out/latest.json(全0=会话陈旧⇒restart容器; 新订阅者收不到tcp_pose); 8793页真源=tools/web/station.html热读
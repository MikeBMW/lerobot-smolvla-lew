Orin=192.168.23.66(tashan/ts123); 产线口.23.50/24无网关(enx00e04c0c32a0); 两机直达工控机.23.23
§
NTP回拨8h(勿动RTC)→节拍用monotonic, 负帧龄拒用
§
分层(老倪): L5定方向造数据/L4认知预测/L3状态调度/L2检测反馈; 主干=SigLIP768d+四头; from-scratch主干必崩
§
交付前先自跑通; GPU不许空转; 改配置/文件必回读核验(替换锚点会静默no-op→我曾假报成功)
§
技能清单少而可分辨; 一切可复制可执行(curl/JSON/图右键)
§
Hermes: 长命令拆多段(内联易截断→写脚本); sudo免密; 开机网络优化=zmax-net-optimize(+6~19%)
§
ssh pkill -f自杀→锚定^python3; L5=DeepSeek Vision(61s→异步旁路; smolvlm2-500m兜底)
§
飞书99991663=gateway token缓存过期→用户重启gateway(agent被禁);兜底feishu_notify.py自换token;长文≥1.5k字→400须拆条
§
引擎tr['obs']39D≠h5 env原生o[:39](跨集先验逐维); L3须env原生obs+128图+post反归一化(u_ff=act×0.5)
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
真机: rt动作后必下电; move_joint/line不下电; 30s超时success=False但动作已成勿重发; collision_detection=False
§
L2.lissa_insert=里萨如力控插入(6N配方,插槽口沿工具Z退60mm→推进→lissajous_force_search); insert_pose=治具插入位
§
真机视: 只起camera/realsense_source(参抄launch); tap→cam_rs.png
§
记忆五层: L2/L3/L4+总装Qwen(SS_MACRO); 势场喂obs[0:3]非peg_head
§
真源: zmax_robot_spec/calib.json→tools/zmax_params.py; 联合训练joint_train_all.py; LoRA=lora_inject.py
§
L5规划器/safety路径=left_right/state_space/{planner,safety}.py; INTACT稳态101ms(10Hz)冷6.7s→须常驻
§
阶段MOE: 学习式门控必坍缩→硬先验路由(--route prior); 判据=单射性
§
LoRA需merge(否则零动作伪装'没提升'): merge_lora_ckpt.py; 判假A/B=逐位同
§
AOI: 10082金手指/10083表面; /capture_detect 200=受理(读/last_result); 判据图=手选框>原图自裁>拉长图; 圈选落盘aoi_console_state.json
§
老倪的APP三条链(勿混): ①手机APP zmax=Android WebView壳(~/state3d_app)→datadrive.world/state-3d.html(ECS静态页,改需SSH密码;本地源tools/gui/state_3d_mobile.html) ②robot-monitor.html读mac分支robot-status.json ③桌面exe=studio.py
§
ECS relay: 3端点upload/latest/status; 包={meta:{source,type:hw_metrics,project,role,machines},data:{machines:{名:{host,cpu,mem,disk,gpu}}}}; ★/latest=最新包覆盖(非按机器存)→多端上传互顶,并存须改ECS; 上传tools/hw_upload_relay.py(4060含显存6s频)
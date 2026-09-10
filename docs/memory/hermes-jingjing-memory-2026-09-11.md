web=4090训练+ComfyUI+前端+ECS部署+PM，总工(4060/GitHub/GUI)，小芳=硬件
§
链路: Orin→Mac→ECS→4060; WSL↔Orin不通→relay_middleware(WS datadrive.world/ws)+Mac守护; scp>100MB断→base64+echo; 模型chmod644
§
系统=E盘p5原生Ubuntu非WSL(09-06克隆迁移); 双系统RTC勿动adjtime
§
画布三级: L4=世界模型(流形JEPA+LEW) / L3=VLM+DiT(smolvla_lew: gripper不准+闭环对布局不鲁棒→SS_L3默认关; 解析链100%/模型0-15) / L2=原子技能SK01-08+行左A/B/C算子; capability_levels.py开头自动回退顶部
§
老倪: 指令最小化(删X=先改名); 画布没用的删干净; 新节点注册node_logic
§
安全限值=🛡类别4栏位; 状态空间唯一三层安全(否决+限幅+Sys0)
§
崩溃铁律: worker线程禁QObject→pyqtSignal回主线程; GUI改码必重启
§
GUI: gui-venv311在仓库内(含torch可训练); 改码必重启; flows/*.json坐标须int; 命令触发/tmp/zmax_nav_cmd; 启动须cd仓库根+完整路径studio.py; 画布编辑铁律: GUI运行中切档会写回state_space_obs.json覆盖编辑→先停全部studio再改再重启, 杀studio用ps -eo pid,args|awk '$2~/gui-venv311\/python$/'+kill; 连线布局须左上→右下, 反向仅反馈回路标↩; 打包--add-data只加真实目录(不存在→构建全挂)
§
GitHub: 直连超时→ghproxy.net代理+sslVerify=false; Release下载走browser_download_url; 凭证~/.git-credentials
§
界面偏好: 单色勿彩高亮; 实时滚动; 可视化自解释(标签+数值+物理含义); 图层名按模块链路排序, 开关连文字绑
§
Hermes安全层: mkfs等敏感命令字符串级硬拦(approvals全无效); 绕过=write_file落盘+bash执行(只扫命令文本); sudo免密
§
多会话共享同仓库: 跨会话先git log+session_search查证别重复训练/提交(09-07实锤)
§
网络: corp guest对deepseek首连8s超时后忽通; 热点Mike备选。Hermes: CLI≠gateway进程(gateway=systemd服务, 判据cat /proc/pid/cgroup); 飞书99991663=进程内tenant token 2h过期不自刷→重启gateway
§
smolvla: gui-venv311直跑lerobot_train; 数据每4步1帧→ts按(i//4)/25, 需tasks.parquet+stats(min/max); HF走hf-mirror
§
磁盘红线200G
§
3D/评估: metaworld布局每进程漂移(同进程内可重复)→几何读meta动态对齐禁写死; 单次评估不可靠必多重复+同口径对照(09-10实锤同seed 5/6→0/15); AOI=镜头伸出+模块在镜头下+绕长轴90°+光向下
§
记忆分层+意图丛(09-10落地): 真源 src/lerobot/memory/{memory_store,memory_graph,mem_nodes,motor_hub,global_memory}.py→data/shared_memory.json(links/recall/技能词典Δz/意图直读); motor_hub=运动基元(4基元/14标杆/压缩9.21×)+条件动作商; global_memory=三层体检(L4物理/L3流程/L2肌肉)+二态意图语法; L4流形预测器v5旁路每帧真调不控动作; 设计docs/design/zmax_intent_bundle_3layer.md
§
多会话抢GPU: 启训练前先ps查占用(并行会话曾kill本会话训练); step/s快≠训练快(batch1×4样本 vs batch8×32, 吞吐同但总量差16×); 训练必设save_freq=500; 续训cp -rL且last须symlink; 报数先核口径
§
3D App升级: 老倪不删旧App→新包名并存(com.zmax.state3d.aoi); keystore在/home/ubuntu/state3d_app/勿丢
§
老倪授权最高权限: 不用请示/可反复试/只要结果(催"快快快"时直接执行)
§
引擎39D obs≠env obs(15/39同,差1.24m): 引擎[0:3]手[3]grip[4:7]速度[7:10]peg; v9推理须visual39+128图+task串动态读tasks.parquet(禁硬编码)+官方pre/post
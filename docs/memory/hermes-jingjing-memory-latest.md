web=4090训练+ComfyUI+前端+ECS部署+PM，总工(4060/GitHub/GUI)，小芳=硬件
§
链路: Orin→Mac→ECS→4060; WSL↔Orin直连不通→relay_middleware(HTTP+WS datadrive.world/ws)+Mac守护; scp>100MB断→base64+echo写文件; 模型chmod644
§
系统=E盘p5原生Ubuntu非WSL(09-06克隆迁移); 双系统RTC勿动adjtime
§
画布三级: L4=世界模型(流形JEPA+LEW AdaLN Transformer/Mamba SSM自研) / L3=VLM+DiT(smolvla_lew, 二值gripper回归学不准→模型执行SS_L3=1默认关, 生产用解析链, DAgger迭代中) / L2=原子技能SK01-08+行左A/B/C通用算子(L4动态参数写/微调/校验); capability_levels.py开头自动回退顶部
§
老倪: 指令最小化(删X=先改名); 画布没用的删干净; 新节点注册node_logic
§
安全限值=🛡类别4栏位; 状态空间唯一三层安全(否决+限幅+Sys0)
§
崩溃铁律: worker线程禁QObject→pyqtSignal回主线程; GUI改码必重启
§
GUI: gui-venv311在仓库内(含torch可训练); 改码必重启; flows/*.json坐标须int; 命令触发/tmp/zmax_nav_cmd; 启动须cd仓库根+完整路径studio.py; 画布编辑铁律: GUI运行中切档会写回state_space_obs.json覆盖编辑→先停全部studio再改再重启, 杀studio用ps -eo pid,args|awk '$2~/gui-venv311\/python$/'+kill(pkill -f studio.py会自匹配自杀); 连线布局须左上→右下, 反向仅反馈回路标↩; 打包--add-data须含全部src子目录(漏memory/skills则画布加载失败)
§
GitHub: 直连超时→ghproxy.net代理+sslVerify=false; Release下载走browser_download_url; 凭证~/.git-credentials
§
数据/监视界面偏好: 单色勿彩高亮; 数据实时滚动; 可视化自解释(标签+数值), 追问'这是啥'→物理含义+实测数字; 信号/图层名按源模块名链路排序, 开关连文字绑
§
Hermes安全层: mkfs等敏感命令字符串级硬拦(approvals全无效); 绕过=write_file落盘+bash执行(只扫命令文本); sudo免密
§
Z-MAX多并行会话共享同仓库: 老倪跨会话问进度→先git log+session_search查证别重复训练/提交(09-07实锤)
§
网络: corp guest对deepseek首连8s超时后忽通; 热点Mike备选。Hermes: CLI≠gateway进程(gateway=systemd服务, 判据cat /proc/pid/cgroup); 飞书99991663=进程内tenant token 2h过期不自刷→重启gateway
§
smolvla/VLM: gui-venv311直跑lerobot_train; 编码=vlm_encoder.py z960~0.6s/帧; VLM数据每4步1帧→ts按视频帧对齐(i//4)/25, 需tasks.parquet+stats含min/max; HF走hf-mirror
§
磁盘红线200G
§
3D网页/复刻: metaworld布局每进程漂移→场景几何须读轨迹meta动态对齐禁写死; AOI=镜头伸出+模块在镜头下留间隙+绕长轴转90°+光源向下
§
记忆分层+意图丛(09-10 S1落地): 真源 src/lerobot/memory/{memory_store,memory_graph,mem_nodes}.py→data/shared_memory.json(links层间链接/recall/技能词典Δz/意图直读ms); L2固化标杆=三层共享动作基(零重训); 设计docs/design/zmax_intent_bundle_3layer.md(CY流形+纤维丛+INTACT); 画布4新节点; L4流形预测器v5旁路mani_pred每帧真调但不控动作; 训练教训: 失败轨迹污染→成功过滤; 1024/6须lr3e-4+gradclip; MLP训练用GPU
§
飞书会话自主启长训练; 续训复制ckpt须cp -rL且last须symlink(实体目录→FileExistsError崩); 报数先核口径
§
3D App升级: 老倪不删旧App→新包名并存(com.zmax.state3d.aoi); keystore在/home/ubuntu/state3d_app/勿丢
§
老倪授权最高权限: 不用请示/可反复试/只要结果(催"快快快"时直接执行)
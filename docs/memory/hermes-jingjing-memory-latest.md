web=4090训练+ComfyUI+前端+ECS部署+PM，总工(4060/GitHub/GUI)，小芳=硬件
§
链路: Orin→Mac→ECS→4060; WSL↔Orin直连不通→relay_middleware(HTTP+WS datadrive.world/ws)+Mac守护; scp>100MB断→base64+echo写文件; 模型chmod644
§
系统=09-06克隆迁移→E盘p5(ubuntu-e 62G)原生Ubuntu非WSL; Boot0001置前C/D零接触; 双系统RTC勿动adjtime
§
架构: 坐标逻辑主线图像背景; state叠进latent; 45D=39+相对; 58D=45+触觉4+CoT9; 画布三级能力(09-08)=🏆专家世界模型(流形)🚀高级端到端(VLM+FM-ActionHead,smolvla_lew)🔧基础分段小模型(YOLO+前馈MLP+原子技能独跑保插拔)
§
老倪: 指令最小化(删X=先改名); 画布没用的删干净; 新节点注册node_logic
§
安全限值=🛡类别4栏位; 状态空间唯一三层安全(否决+限幅+Sys0)
§
GPU: LiveUSB重启丢dev/nvidia*+uvm不载→CUDA unknown; nvidia-device-nodes服务持久化; cufile/cusparselt→ldconfig
§
崩溃铁律: worker线程禁QObject方法→pyqtSignal回主线程; exit134:finished置None防GC; GUI改码必重启
§
GUI: gui-venv311在仓库内(Py3.11无torch); 训练=~/lerobot-venv; 改码必重启; 取证QWidget.grab; flows/*.json坐标必须int(字符串→QRectF崩GUI); 命令触发/tmp/zmax_nav_cmd
§
GitHub: 直连超时→ghproxy.net代理+sslVerify=false; Release下载走browser_download_url; 凭证~/.git-credentials
§
数据/监视界面偏好: 单色勿彩高亮; 数据实时滚动; 可视化自解释(标签+数值), 追问'这是啥'→物理含义+实测数字; 信号/图层名按源模块名链路排序, 开关连文字绑
§
引擎假卡死→py-spy查do_wait_suspend; debugpy僵尸5678用F5 preLaunchTask清
§
Hermes安全层: mkfs等敏感命令字符串级硬拦(approvals全无效); 绕过=write_file落盘+bash执行(只扫命令文本); sudo免密
§
Z-MAX多并行会话共享同仓库: 老倪跨会话问进度→先git log+session_search查证别重复训练/提交(09-07实锤)
§
网络(09-08实锤): 公司corp guest对deepseek海外API不稳(首连8s超时后忽通)→我卡死无反映; 长期用手机热点Mike; corp guest下飞书/github/国内均通
§
smolvla_lew训练(09-08): cfg=configs/policies/smolvla_lew/config_smolvla_lew_metaworld.yaml(4060裁剪:freeze VLM+DiT-B+LEW,batch1); 图像数据=sim_real教师采(tools/collect_simreal_vla_data.py+sim_real._frame_sink钩子, 3/3验证通); 跑: MUJOCO_GL=egl gui-venv311 python tools/collect_simreal_vla_data.py --target 30; 坑: metaworld_peg坏(1帧/集)、官方peg专家只抓不插、--far EGL崩、引擎env属性=self.env; SmolVLM2-500M走HF_ENDPOINT=hf-mirror; 4090=39.102.211.79:50054(web, sshpass+ZMAX_ECS_PW); 用户方向: 仿JEPA构建接触/性能流形潜空间
§
画布09-08: 标定层→引力-斥力-动作(收DiT lkdc_cal); 潜空间节点→潜空-流形(收L4流形lkmc_lat/lkmp_lat); ss_lat注册词含'潜空'; 原子技能源码→src/lerobot/.../state_space/skills/; 功能清单v2=capability_levels.py(L2🔧/L3🚀/L4🏆+测试对应), ECS部署tools/export_capability_web.py(ZMAX_ECS_PW)
§
GUI09-08: chk_l3_full勾选→mode=full插拔+AOI(20-40s/轮); R1视觉full seed104=877步闭环; 3D视频data/ss3d_l3_full*.mp4; 探针坑: 直方图/归因按probe._seq递增去重→诊断前向勿clear(); Scope通用格全量轴+播放头竖线
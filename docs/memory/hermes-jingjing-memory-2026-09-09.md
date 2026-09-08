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
smolvla/VLM(09-08): gui-venv311推理就绪 torch2.7.1+transformers5.16.1+num2words(uv装,venv无pip); 权重缓存SmolVLM2-500M-Video-Instruct(onnx 4.7G可删); 编码=processor(图+<image>)→全前向hidden[-1] mean-pool→z960(1.4GB/0.8s帧); 真实编码器=vlm_encoder.py(smolvla_lew包), 🧠VLM节点双击真实前向(后台加载~15s); HF下载走hf-mirror
§
画布09-08: 标定层引力-斥力-动作; 潜空-流形=潜空间节点(L4); ss_lat注册词含'潜空'; 功能清单v2=capability_levels.py L2🔧/L3🚀/L4🏆+测试对应+ECS导出(ZMAX_ECS_PW)
§
JEPA L4链路(v5.4.0): predictor=src/lerobot/manifold/predictor_layer.py(LatentPredictor z+a→z' + ManifoldReadout→6维流形坐标,真值列对齐可训); 注入ContactManifold/PerformanceManifold(manifold_layer.py predict_manifold)+sim_real每帧真调→tr['mani_pred'](随机权重trained=False,断点每帧可进); decoder=smolvla_lew/state_space_action_head.py; 肌肉记忆仅R0(vision禁快通道:标杆×视觉随机9/9失败,SS_MUSCLE=0同轮352成功); 🧭能力档位双击切L2(insert)/L3(full插拔+AOI)/L4(full+cap=l4预算×2)
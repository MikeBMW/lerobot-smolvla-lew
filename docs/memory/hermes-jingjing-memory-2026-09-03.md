web=4090训练+ComfyUI+前端+ECS部署+PM，我是总工(4060/GitHub/GUI)，小芳=硬件(Mac/Orin/飞书)
§
链路: Orin(.66)→Mac→ECS→4060; WSL↔Orin直连不通→relay_middleware(HTTP+WS wss://datadrive.world/ws)→Mac守护→ssh Orin; scp>100MB断→base64+echo写文件; 模型chmod644
§
ECS SSH密码=Nix19789(08-22实测有效,08-13"失效"是网络被墙误判); git push不自动部署; 网页新功能放分页不动主页
§
架构(08-08): 坐标=逻辑主线,图像=背景; state叠进latent; 🧩结构条件(每模型行); 45D=39+相对向量; 58D=45+触觉4+CoT9(08-10); 39D结构=node_logic.node_obs39
§
老倪: 指令最小化(删X=先改名); 画布没用的删干净; 新节点注册node_logic
§
磁盘铁律(硬性): 不允许增加; 红线80G+disk_redline.sh cron每2h清(每目录留最后ckpt)
§
安全限值=🛡类别4栏位; 状态空间唯一三层安全(否决+限幅+Sys0)
§
GPU: 驱动580.126.09; LiveUSB重启/dev/nvidia*节点丢+nvidia_uvm不加载→CUDA unknown error; 服务nvidia-device-nodes+nvidia-uvm-nodes持久化; torch2.7.1+cu128 cufile/cusparselt→ldconfig; LiveUSB无swap内存顶满直接冻结(无OOM日志)→swapfile防御
§
模型引擎=容器框架: 三模式(远程/本地/端侧); Start/Stop=清队列+kill; 本地=强制容器(config root转/app/data/)
§
崩溃铁律: worker线程禁QObject方法(showMessage/setText,跨线程析QTimer→SIGSEGV)须_oneshot或pyqtSignal.emit回主线程(QTimer.singleShot跨线程不触发); exit134:finished置None防GC
§
报告/PDF: 中文字体=wqy-microhei(Noto CFF reportlab不认); GUI转PDF走.venv子进程; TBL全Paragraph; 专家85%锚点不排名
§
视频生成: 停滞检测(120步换seed); 最新模型全失败自动回退; 训练完自动出视频+飞书+PDF
§
能力库model_feature.py v4.1: 7域65能力,ID前缀统一; SCENES=8场景46需求
§
GUI: gui-venv311(Py3.11); 推理/训练=~/lerobot-venv(uv建无pip→uv pip install --python); 项目无.venv; PyQt5枚举错位(传int); Pillow持GIL→子进程; 改完代码必重启studio.py; 禁QT_SCALE_FACTOR
§
GitHub(08-28): 直连已通不走代理(ghproxy证书失效/ghfast作废); Release下载走browser_download_url(asset API带token返400); 凭证~/.git-credentials; 视频/权重不进库
§
数据/监视界面偏好: 单色勿彩高亮; 数据实时滚动; 可视化自解释(标签+数值面板), 追问'这是啥'→给物理含义+实测数字; 信号/图层名用源模块名按链路排序, 开关连文字绑
§
GUI数据总线=DataBusTrace 14模块51接口
§
可视化/控制铁律(v3.2.0): 画前先算信噪比(噪声5mm vs 步位移0.35mm→瞬时值必乱,改画多帧均值+系统占比%); 凸组合遇量级差21倍=砍速到29%→前馈+反馈相加+显式阶段限速; 反馈前残差EMA; 详见zmax-console技能
§
3D视图=程序执行映射(09-02): 运行后优先sim.run()轨迹,_ss_tick每帧set_frame推idx,断点停=3D停; 无运行才退episode; shader绑首GL→窗口只复用不新建; 打开即自动播放
§
引擎断点挂起=假卡死→py-spy查do_wait_suspend; debugpy僵尸pydevd占5678→attach SystemExit:1(ss查kill)
§
状态空间: target=obs[36:39]感知层写(仿真HOLE_POS/真机YOLO)非世界模型; parallel.py=画布解析式,源码_EXTERNAL_LOC映射; ss_ff/ss_est共用node_ss_s2
§
标定层v3.4.4: src/lerobot/calibration/ 引力(动作:Kp+阶段速度上限)vs斥力(状态预测:K/EMA/接触增益/否决阈值)平衡偏差=引力势−斥力势; 画布最下, 右键表格编辑
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
GPU: 驱动580.126.09; LiveUSB重启/dev/nvidia*节点丢+nvidia_uvm不加载→CUDA unknown error; 服务nvidia-device-nodes+nvidia-uvm-nodes持久化; torch2.7.1+cu128 cufile/cusparselt→ldconfig
§
模型引擎=容器框架: 三模式(远程/本地/端侧); Start/Stop=清队列+kill; 本地=强制容器(config root转/app/data/, VLA-Touch/AWE也容器)
§
崩溃铁律: worker线程禁QObject方法(showMessage/setText,跨线程析QTimer→SIGSEGV)须_oneshot或pyqtSignal.emit回主线程(QTimer.singleShot跨线程不触发); exit134:finished置None防GC
§
报告/PDF: 中文字体=wqy-microhei(Noto CFF reportlab不认); GUI转PDF走.venv子进程; TBL全Paragraph; 专家85%锚点不排名
§
modelzoo工程~/lerobot-modelzoo/(七模型configs+scripts容器训练)
§
视频生成: 停滞检测(120步换seed); 最新模型全失败自动回退; 训练完自动出视频+飞书+PDF(5s后on_insert_report)
§
hermes_core备份在~/(/workspace已无); 恢复见hermes-crash-recovery技能
§
能力库model_feature.py v4.1: 7域65能力,ID前缀统一; SCENES=8场景46需求
§
GUI: gui-venv311(Py3.11); 推理/训练=~/lerobot-venv(uv建无pip→uv pip install --python); 项目无.venv; PyQt5枚举错位(传int); Pillow持GIL→子进程; 改完代码必重启studio.py; 禁QT_SCALE_FACTOR
§
GitHub(08-28): 直连已通不走代理(ghproxy证书失效/ghfast作废); Release下载走browser_download_url(asset API带token返400); 凭证~/.git-credentials; 视频/权重不进库
§
数据/监视界面偏好: 单色显示勿大面积彩色高亮; 数据须实时滚动非静态填充; 可视化必须自解释(标签+数值面板), 他会追问'这是啥'→答案要给物理含义+实测数字; 信号/图层名用源模块名+按链路排序, 开关须连文字一起绑
§
GUI数据总线=DataBusTrace 14模块51接口; 右键视觉行=metaworld 7视角
§
可视化/控制铁律(v3.2.0): 画前先算信噪比(噪声5mm vs 步位移0.35mm→瞬时值必乱,改画多帧均值+系统占比%); 凸组合遇量级差21倍=砍速到29%→前馈+反馈相加+显式阶段限速; 反馈前残差EMA; 详见zmax-console技能
§
3D视图=操作视频同源(v3.3.0): 六层直驱metaworld出trace+mp4, 相机corner2四元数(fov水平), 八阶段状态机图层; Release双平台exe+mac; ⚠️pyqtgraph shader全局缓存绑定首GL上下文→3D窗口只复用不新建, 重建场景按id去重removeItem
§
VSCode调试: F5默认🚀全新调试进程(launch新实例); attach 5678备用(控制台启动即listen不阻塞); 右键开VSCode写launch.json 3配置+g定位源码
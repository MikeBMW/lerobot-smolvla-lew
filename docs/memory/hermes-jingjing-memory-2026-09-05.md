web=4090训练+ComfyUI+前端+ECS部署+PM，总工(4060/GitHub/GUI)，小芳=硬件
§
链路: Orin(.66)→Mac→ECS→4060; WSL↔Orin直连不通→relay_middleware(HTTP+WS wss://datadrive.world/ws)→Mac守护→ssh Orin; scp>100MB断→base64+echo写文件; 模型chmod644
§
ECS SSH密码=Nix19789(08-22实测有效); git push不自动部署; 网页新功能放分页不动主页
§
架构: 坐标=逻辑主线,图像=背景; state叠进latent; 🧩结构条件; 45D=39+相对向量; 58D=45+触觉4+CoT9
§
老倪: 指令最小化(删X=先改名); 画布没用的删干净; 新节点注册node_logic
§
磁盘铁律(硬性): 不允许增加; 红线80G+disk_redline.sh cron每2h清(每目录留最后ckpt)
§
安全限值=🛡类别4栏位; 状态空间唯一三层安全(否决+限幅+Sys0)
§
GPU(580.126.09): LiveUSB重启丢dev/nvidia*+uvm不载→CUDA unknown; nvidia-device-nodes服务持久化; cufile/cusparselt→ldconfig; swap见技能
§
模型引擎=容器框架: 三模式(远程/本地/端侧); Start/Stop=清队列+kill; 本地=强制容器(config root转/app/data/)
§
崩溃铁律: worker线程禁QObject方法(跨线程析QTimer→SIGSEGV)须_oneshot或pyqtSignal.emit回主线程(singleShot跨线程不触发); exit134:finished置None防GC
§
报告/PDF: 中文字体=wqy-microhei(Noto CFF reportlab不认); GUI转PDF走.venv子进程; TBL全Paragraph; 专家85%锚点不排名
§
视频: 停滞检测(120步换seed); 全失败自动回退; 完事自动视频+飞书+PDF
§
能力库: node_func_tree.py 21域110功能(v4.2)
§
GUI: gui-venv311在仓库内(Py3.11,无torch); 推理/训练=~/lerobot-venv; 项目无.venv; PyQt5枚举错位(传int); Pillow持GIL→子进程; 改码必重启studio.py; 禁QT_SCALE_FACTOR
§
GitHub: 直连不走代理; Release下载走browser_download_url(asset带token返400); 凭证~/.git-credentials
§
数据/监视界面偏好: 单色勿彩高亮; 数据实时滚动; 可视化自解释(标签+数值), 追问'这是啥'→物理含义+实测数字; 信号/图层名按源模块名链路排序, 开关连文字绑
§
GUI数据总线=DataBusTrace 14模块51接口
§
可视化/控制铁律(v3.2.0): 画前先算信噪比(噪声5mm vs 步位移0.35mm→瞬时值必乱,改画多帧均值+系统占比%); 凸组合遇量级差21倍=砍速到29%→前馈+反馈相加+显式阶段限速; 反馈前残差EMA; 详见zmax-console技能
§
3D视图=程序执行映射(09-02): 运行后优先sim.run()轨迹,_ss_tick每帧set_frame推idx,断点停=3D停; 无运行才退episode; shader绑首GL→窗口只复用不新建; 打开即自动播放
§
引擎断点挂起=假卡死→py-spy查do_wait_suspend; debugpy僵尸占5678已根治(F5 preLaunchTask自动清lsof:5678)
§
状态空间: ▶运行默认真实化=state_space_sim_real.py(每帧render→YOLO,detect_3d断点每步进); ⚡引擎快演=0.1s演示; 锚=obs hand(site低4cm); 红线: 每帧渲染,节流/冻结/复用旧值=造假
§
标定层v3.4.5闭环: apply_to_engine写回引擎源码字面量(cognition V_CAP/MIN+veto/k_fb, sim校正K/接触增益/安全限幅/先验A/EMA; parallel Kp仅守卫回退); importlib重载→▶运行生效; stage dict写回须块内(防V_MIN串V_CAP); prior_A=1.0真值
§
⚡前馈(09-04): 547K蒸馏MLP主执行+域外解析守卫D_GUARD0.25; 数据管道教师固定解析; sim几何改→重跑重训, 详见zmax-left-right-policy
§
仿真术语(09-04): peg/插销=光模块(表述+YOLO类名det键已改); 代码变量/site名保留; 覆写names须底层model.model.names(顶层无效)
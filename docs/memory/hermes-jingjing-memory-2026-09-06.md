web=4090训练+ComfyUI+前端+ECS部署+PM，总工(4060/GitHub/GUI)，小芳=硬件
§
链路: Orin→Mac→ECS→4060; WSL↔Orin直连不通→relay_middleware(HTTP+WS datadrive.world/ws)+Mac守护; scp>100MB断→base64+echo写文件; 模型chmod644
§
ECS SSH密码=Nix19789(08-22实测有效); git push不自动部署; 网页新功能放分页不动主页
§
架构: 坐标=逻辑主线,图像=背景; state叠进latent; 45D=39+相对; 58D=45+触觉4+CoT9
§
老倪: 指令最小化(删X=先改名); 画布没用的删干净; 新节点注册node_logic
§
磁盘铁律: 红线80G+disk_redline.sh cron每2h清(每目录留最后ckpt)
§
安全限值=🛡类别4栏位; 状态空间唯一三层安全(否决+限幅+Sys0)
§
GPU: LiveUSB重启丢dev/nvidia*+uvm不载→CUDA unknown; nvidia-device-nodes服务持久化; cufile/cusparselt→ldconfig
§
模型引擎=容器三模式(远程/本地/端侧); 本地强制容器(config root→/app/data)
§
崩溃铁律: worker线程禁QObject方法(跨线程析QTimer→SIGSEGV)须_oneshot或pyqtSignal.emit回主线程(singleShot跨线程不触发); exit134:finished置None防GC
§
报告/PDF: 中文字体wqy-microhei(Noto CFF不认); GUI转PDF走.venv子进程; TBL全Paragraph; 专家85%锚点不排名
§
GUI: gui-venv311在仓库内(Py3.11,无torch); 推理/训练=~/lerobot-venv; 项目无.venv; PyQt5枚举错位(传int); Pillow持GIL→子进程; 改码必重启studio.py; 禁QT_SCALE_FACTOR
§
GitHub: 直连超时→ghproxy.net代理+sslVerify=false; Release下载走browser_download_url; 凭证~/.git-credentials
§
数据/监视界面偏好: 单色勿彩高亮; 数据实时滚动; 可视化自解释(标签+数值), 追问'这是啥'→物理含义+实测数字; 信号/图层名按源模块名链路排序, 开关连文字绑
§
可视化/UI铁律: 画前算信噪比(噪声5mm vs步移0.35mm→画多帧均值+占比%); 凸组合量级差21倍→砍速29%(前馈+反馈相加+显式限速); 反馈前残差EMA; 老倪UI严审(直方图被打回3轮): Qt高分屏192dpi文字须QRect TextWordWrap+fontMetrics流式行高, QFont pt/坐标须int(float崩整窗), 直方图禁连线(像波形), 关窗单例sip.isdeleted重建; 播放=demo不跑真实fn→可视化靠引擎每步probe_seq(两引擎都加)同游标逐帧push三窗
§
3D=程序执行映射: 优先sim.run()轨迹,_ss_tick逐帧set_frame同步; 无运行退episode(标题标注EPISODE回放); shader绑首GL窗口只复用
§
引擎断点挂起=假卡死→py-spy查do_wait_suspend; debugpy僵尸5678: F5 preLaunchTask自动清lsof
§
状态空间: ▶运行默认真实化(逐帧render→YOLO,detect_3d断点每步进); ⚡引擎快演=简化引擎; 锚=obs hand; 红线: 节流/冻结/复用旧值=造假
§
标定层v3.4.5闭环: apply_to_engine写回引擎源码字面量(cognition V_CAP/MIN+veto/k_fb, sim校正K/接触增益/安全限幅/先验A/EMA; parallel Kp仅守卫回退); importlib重载→▶运行生效; stage dict写回须块内(防V_MIN串V_CAP); prior_A=1.0真值
§
⚡前馈(09-04): 547K蒸馏MLP主执行+域外解析守卫D_GUARD0.25; 数据管道教师固定解析; sim几何改→重跑重训, 详见zmax-left-right-policy
§
仿真术语(09-04): peg/插销=光模块(表述+YOLO类名det键已改); 代码变量/site名保留; 覆写names须底层model.model.names(顶层无效)
§
验收(09-05): 唯一指标=插入成功+插入段<0.5s+横向错位<0.5mm(12扰动集PASS; 引擎:孔壁yz对中+孔底止动+insert_depth 4→0.5mm+cap0.085); Scope插深剩余/横偏格+0.5mm红线+底部✅摘要; 可视化节点双击/右键开窗(viz_kind参数), 无数据自动先跑引擎
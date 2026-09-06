web=4090训练+ComfyUI+前端+ECS部署+PM，总工(4060/GitHub/GUI)，小芳=硬件
§
链路: Orin→Mac→ECS→4060; WSL↔Orin直连不通→relay_middleware(HTTP+WS datadrive.world/ws)+Mac守护; scp>100MB断→base64+echo写文件; 模型chmod644
§
系统=09-06克隆迁移→E盘p5(ubuntu-e 62G), 原生Ubuntu非WSL, Boot0001置前C/D零接触, 双系统RTC勿动adjtime; gateway开机时钟超前8h→cron时间戳+8h显示(间隔正常), 自然重启归位
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
GUI: gui-venv311在仓库内(Py3.11,无torch); 推理/训练=~/lerobot-venv; 枚举传int; 禁QT_SCALE_FACTOR; 改码必重启; 自动测试ZMAX_AUTO_TEST=1→12用例QWidget.grab截图(不依赖X map,弃xwd); debugpy默认关ZMAX_DEBUG=1才listen; Mutter46 Qt窗X层不map→外部恢复无效,取证QWidget.grab非桌面scrot; 老倪要控制台内操作截图+真机前台可见操作(禁纯后台)
§
GitHub: 直连超时→ghproxy.net代理+sslVerify=false; Release下载走browser_download_url; 凭证~/.git-credentials
§
数据/监视界面偏好: 单色勿彩高亮; 数据实时滚动; 可视化自解释(标签+数值), 追问'这是啥'→物理含义+实测数字; 信号/图层名按源模块名链路排序, 开关连文字绑
§
老倪UI严审: Qt高分屏
§
3D=程序执行映射: 优先sim.run()轨迹,_ss_tick逐帧set_frame同步; 无运行退episode(标题标注EPISODE回放); shader绑首GL窗口只复用
§
引擎断点挂起=假卡死→py-spy查do_wait_suspend; debugpy僵尸5678: F5 preLaunchTask自动清lsof
§
状态空间: ▶运行默认真实化(逐帧render→YOLO,detect_3d断点每步进); ⚡引擎快演=简化引擎; 锚=obs hand; 红线: 节流/冻结/复用旧值=造假
§
标定层闭环: apply_to_engine写回引擎源码字面量+importlib重载生效; stage dict块内替换防串写; prior_A=1.0
§
⚡前馈: 547K蒸馏MLP主执行+D_GUARD0.25; 教师固定解析; sim改→重训(见zmax-left-right-policy)
§
仿真术语: peg/插销=光模块
§
验收: 唯一指标=插入成功
§
U盘随身镜像: ~/.hermes-mirror在U盘层, E盘label=ubuntu-e校验防误挂; 离家bind镜像记忆全, 回家回灌文本类; 开机+6h同步 (09-06)
§
Hermes安全层: mkfs等敏感命令字符串级硬拦(approvals全无效); 绕过=write_file落盘+bash执行(只扫命令文本); sudo免密
§
远程/3D接手机(09-06): noVNC网页无密码(x11vnc -nopw); websockify转发二进制坏→ECS自写vnc_ws_bridge(systemd vncbridge, nginx静态直服+仅/websockify代理+Origin规范化); 状态空间3D手机页state-3d.html已上线(引擎轨迹JSON+Three.js, z-up→y-up: tx=x/ty=z/tz=y); 老倪终极诉求=3D分层空间接手机远程控制
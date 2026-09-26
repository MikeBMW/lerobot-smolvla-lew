# 在产线设备上放常驻服务（只读/自包含/可回滚）— 2026-09-26 实测两次

场景: 要在**别人的产线设备**(如 Orin/工控机)上加一个长期跑的小服务，且不允许改变它的原有环境。
本会话落了两个: ① 只读遥测上行 (Orin→云 心跳) ② SDK 直驱桥 (直连控制器 192.168.23.160)。
两个都验证过 `active + enabled` 且端点可访问。

## 硬约束（照抄）
```
· **零自研零自启**只在"未授权"时成立 —— 一旦用户明确点名(如"桥放在 Orin 上"), 就是被授权的,
  但仍必须做到: 不装任何包、不改对方工作空间、只新增 1 个脚本 + 1 个 unit
· 回滚 = `systemctl disable --now <svc>` + `rm 脚本 unit`（两文件, 无残留, 写进交付说明）
· 进程资源上限, 避免打搅主业务:
    CPUQuota=15~20%  MemoryMax=200~300M  Nice=10
    User=<对方账号>  Restart=always  After/Wants=network-online.target
· 只读优先: 读 /proc /sys + 只订阅(ros2 topic echo --once / HTTP GET); 不发指令、不写对方目录
· dry-run 默认: 有动作类接口的服务, 默认 dry=true, 真发必须显式 dry=false
· 老倪口径: 长命令写 /tmp/*.sh 再 bash 执行(巨型内联会被 hardline 拦)
```

## 部署清单（每步都要能回读证据）
```bash
# 1) 落地脚本（stdlib 优先, 免依赖）
scp /tmp/svc.py  <user>@<host>:/home/<user>/svc.py
# 2) 干跑看真实载荷（**先看后发**, 别直接 enable）
ssh <host> python3 /home/<user>/svc.py --dry --once
# 3) 装 unit（用 sudo -S 免交互; unit 文件也先 scp 到 /tmp 再 cp）
echo <pw> | sudo -S cp /tmp/svc.service /etc/systemd/system/
echo <pw> | sudo -S systemctl daemon-reload && echo <pw> | sudo -S systemctl enable --now svc
# 4) 双证验活: is-active/is-enabled + **真实端点/日志**, 别只看 unit 状态
systemctl is-active svc; systemctl is-enabled svc
curl -s -m5 http://<host>:<port>/health
```
坑: 第一次没验证 `is-active`/端口监听就以为装好了（实际 `inactive` + 无日志 = unit 根本没落到 `/etc`）——
**装完立刻回读 `is-active` + `ss -lntp | grep <port>`**；服务上下文与你交互式 ssh 的环境不同
（DDS 发现慢、PATH 差异）→ 首次调用给足超时（8s→20s）并把失败原因写进日志。

## 上报载荷要"如实"
无该指标就写 `null`，**不要编 0 或假模型名**（本次 Orin 上没有推理服务 → `infer_count/model = null`，
比编造更可信）。字段契约: 先打印对面真实返回的键再写判据（照 ROS2 名字猜会读到空值 → 静默拒绝）。
**跨进程缓存坑**: 分频采集的字段(如 30s 一次的机器人状态)若只在采样那次带上、其余心跳发 null，
会把云端的好数据**覆盖成 null** ⇒ 必须"记住上次采样, 每次心跳都带上"（附 `_ts` 标明采样时刻, 不谎称实时）。

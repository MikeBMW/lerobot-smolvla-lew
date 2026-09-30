# 采集/上报进程的常驻化（本机侧）—— systemd > setsid

补 `SKILL.md` §5（那里只讲到 `setsid`，解决「SSH 断开」；
本文解决「agent 会话结束 / 脚本被切分支带走 / 机器重启」）。
多生产者写同一个"最新包"槽位互相顶掉的问题见 `multi-producer-telemetry-slot.md`，本文不重复。

## 症状 → 用户视角
界面持续显示**「等待上报 / 等待上传」**，而你以为上报一直在跑。
实测根因：上报进程早就停了，**日志最后一行停在几十分钟前**。

## 三个死法（任何一个都足以让"我以为在跑"变成"其实停了"）
1. **临时后台进程随 agent 会话 / 父 shell 一起消失**
   （`nohup … &`、`setsid … &` 都挡不住 agent 侧会话结束）
2. **脚本放在 git 工作区里** → 你一切分支、或 `git stash -u`，文件就被切走/吞进 stash
   可观测症状：服务日志刷
   `can't open file '/…/tools/<uploader>.py': [Errno 2] No such file or directory`
3. **没有 `enable`** → 机器重启后彻底静默，且无人发现

## 正确姿势
```bash
# ① 脚本先落到**工作区之外**的稳定路径（关键：切分支/stash 都不会动它）
git show main:tools/<uploader>.py > /home/ubuntu/<uploader>.py
```
```ini
# /etc/systemd/system/<name>.service
[Unit]
Description=<what it uploads> → relay
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu
ExecStart=/usr/bin/python3 /home/ubuntu/<uploader>.py --watch 3    # ★ 仓库外路径
Restart=always
RestartSec=5
StandardOutput=append:/var/log/<name>.log
StandardError=append:/var/log/<name>.log
[Install]
WantedBy=multi-user.target
```
```bash
sudo cp <name>.service /etc/systemd/system/ && sudo systemctl daemon-reload
sudo systemctl enable --now <name>
# ② 三连验证（缺一条都可能"以为在跑其实没跑"）
systemctl is-active  <name>    # active
systemctl is-enabled <name>    # enabled（开机自启）
tail -3 /var/log/<name>.log    # ★ 时间戳在推进才是真在跑
```

## 频率 ↔ 进程形态（别硬凑）
| 需求频率 | 用什么 | 理由 |
|---|---|---|
| **秒级**（3~6s，抢中转槽位、避免被别的生产者顶掉） | **systemd 常驻服务** | cron 最小 1 分钟粒度，做不到；临时进程会死 |
| **分钟级**（2 分钟，刷公网 raw JSON） | `no_agent` cron | 够用，自带日志与失败告警 |

两条链路**可以并存**：cron 保"零安装网页"的 raw JSON，常驻服务保"中转槽位"的秒级新鲜度。
交付说明里写明**"已做成开机自启服务"** —— 用户才知道它不依赖你的会话。

## 排查口诀
用户说"上报停了"时：
- **先看日志时间戳是否在推进**，不要只看进程是否存在
  - 进程在、日志停 → 卡死/异常被吞（去查上游超时与异常处理）
  - 进程不在 → 按 §11 的方式把它拉起来
- 用 `systemctl status` 看退出码与重启次数（`Restart=always` 生效时可看到自愈记录）

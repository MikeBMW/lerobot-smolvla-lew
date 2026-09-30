---
name: systemd-boot-services
description: "Use when 把脚本做成开机自启/常驻服务, 或 unit 起不来要排查。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [systemd, boot, autostart, service, sysctl, verification, linux]
    related_skills: [linux-host-maintenance, linux-network-perf-boot, zmax-console]
---

# 把本机能力落地成"开机就跑 / 常驻"的服务 (落地 + 核验 + 坑)

## When to Use
- 用户说"以后每次开机都要做 X / 做成常驻 / 开机自启 / 加个服务"。
- 要把一次性的脚本(优化、监听、采集、推图、巡检)变成**不需要人记得跑**的东西。
- 服务起不来、日志是空的、`systemctl start` 没反应 —— 排查口径见 §4/§5。

## 1. 先选形态 (别把一次性的事做成常驻, 也别把常驻的事塞进开机脚本)
| 需求 | 形态 | 说明 |
|---|---|---|
| 内核参数/网络旋钮 | `/etc/sysctl.d/99-<名>.conf` | systemd-sysctl 开机自动应用, **不用写 unit**; 文件里写清"为什么留这条" |
| 开机跑一次就完(优化/预热/体检/台账) | unit `Type=oneshot` + `RemainAfterExit=yes` | `WantedBy=multi-user.target`, `After=network-online.target` |
| 长期在跑(监听/推流/守护) | unit `Type=simple` + `Restart=always` + `RestartSec=10` | 例子: AOI 裁减图实时推飞书 |
| 需要桌面/窗口/X 会话 | unit `Type=simple` + `Restart=no` | **GUI 只人工启动** (用户明确口径, 见 §5); 开机拉起用一次性启动脚本 + 存活盯, 不靠 Restart |

## 2. 三件套 (幂等, 可回滚)
```
/etc/sysctl.d/99-<名>.conf          # 只有内核参数才需要
<repo>/tools/<名>.sh                # 真逻辑: 应用 + 断言生效值 + 体检 + 落台账; 支持 --quick 等开关
/etc/systemd/system/<名>.service    # 薄壳: 只 ExecStart 调脚本, 不写业务逻辑
```
- **单一真源**: `ExecStart` 指向**仓库里的脚本**(git 可追溯)。不要再拷一份到 `/usr/local/bin` —— 两份副本必然漂移; 真要部署副本, 就在技能里写明"改完要重跑安装器"。
- 安装器做成脚本(可重复跑): `install -m644` / `install -m755` → `systemctl daemon-reload` → `enable --now` → **语法预检 `bash -n`** → 打印 `is-enabled/is-active`。
- 回滚一条命令写进 SKILL.md 交付说明: `systemctl disable --now X && rm /etc/sysctl.d/99-X.conf && sysctl --system`。

## 3. 核验 = 四件事都要有 (缺一件就是"看起来起了")
```bash
systemctl is-enabled <name>.service      # 开机会不会自动跑
systemctl is-active  <name>.service      # 现在活着吗
sudo tail -5 /var/log/<name>.log         # 它自己说了什么 (不是"我以为")
journalctl -u <name>.service -n 20 --no-pager   # 起不来时的真原因
ls -lt <repo>/reports/<名>_*.jsonl       # 真产物: 每跑一次追加一行台账
```
**手工复跑必须走同一代码路径**(`systemctl restart <name>` 而不是手动 `bash 脚本`)—— 否则你验证的不是开机那条路。
一键核验: `scripts/verify_service.sh <unit名> [日志路径] [台账glob]`。

## 4. Pitfalls (全是实测踩过的)
| 坑 | 症状 | 修法 |
|---|---|---|
| 脚本没有可执行位 | unit `status=203/EXEC`, 无日志 | `chmod 755 <脚本>` (write_file 落地默认不是 +x) |
| `RemainAfterExit=yes` 时 `start` 不重跑 | 改了脚本, `systemctl start` 却没有任何新日志 | 用 `systemctl restart` |
| Python 输出被缓冲 | 日志文件**空的**, 但进程明明在跑 | unit 里 `Environment=PYTHONUNBUFFERED=1` (print/watch 型脚本必须) |
| 日志不知道去哪 | `journalctl` 里没有业务输出 | 显式 `StandardOutput=append:/var/log/<名>.log` + `StandardError=append:...` |
| 开机竞态 | unit 起来了但网还没好, 首轮全失败 | `After=network-online.target` + `Wants=network-online.target`, 脚本内每步带超时且失败不阻塞开机 |
| 失败拖死开机 | 机器卡在启动 | oneshot 脚本只做"尽力而为"(`|| true` + 单项超时), 用 `SuccessExitStatus=0 1` 兜住非致命退出 |
| GUI 被"自动重启"骚扰 | 关掉窗口 5s 又弹回来 | GUI unit 一律 `Restart=no` (用户 2026-09-17 定档: 控制台只人工启动) |
| 改完 sysctl 不核验 | 以为生效 | 脚本里改完立刻 `sysctl -n` 打印真值, 并写进台账 |
| 目标路径写死机器名/临时目录 | 换机器就崩 | 路径全部绝对且来自仓库根; 临时脚本放 `/tmp` 但**仓库留档一份** |
| **依赖写成 `Requires=`** | 重启被依赖方会**连带重启**依赖方 | `Requires=` 是双向生命线(停/重启都传播)。若依赖方的"身份"是**启动时才生成**的(内网穿透的公网 URL、会话级地址/端口、一次性 token), 硬依赖会把它换掉 ⇒ 已发出去的链接、已烧进客户端的地址**全部失效**。定式: 用 `Wants=`(软依赖), 只有确实要"被依赖方死了我也停"时才用 `Requires=`。排查症状: 服务全 `active`、本地直连正常、而**经中间那条链路稳定失败** |
| 只测一条链路就下结论 | 本地 ok / 经代理失败 | 本地与服务状态都绿时, **先查中间层自己的状态**(隧道日志里的当前 URL、代理日志里的拒绝原因)——中间层会自己换地址/自己拒绝, 不是被服务的错 |

## 5. 交付口径 (用户拿它当结果看)
- 报告只写四样: **磁盘上的文件路径** · **`is-enabled/is-active` 真值** · **日志/台账一行真输出** · **回滚一条命令**。
- 不许写"已配置完成/已优化"而无数字; 未实测的东西标明"未证明"。
- 需要每次开机都跑的东西, 明确回答"重启后会不会自动跑"(=is-enabled), 而不是"我手动跑过了"。

## 6. 非 systemd 的目标机 (Windows 工控机/产线设备)
同口径落到**计划任务**: 开机常驻 = `/sc onstart /ru SYSTEM /rl highest`, 分钟级保活/自愈 = `/sc minute /mo 1`;
脚本用纯 ASCII (PS 5.1 读无 BOM 的 UTF-8 会把中文解析成乱码), 启动一律 `WScript.Shell.Run("cmd /c cd /d <dir> && <python> <脚本> > <日志> 2>&1", 0, $false)` 分离启动。
看门狗/独占设备/无人升级的完整口径见 `references/production-device-service-pattern.md`。

## 常驻脚本在 agent 会话里起的坑 (2026-09-27 实测)

- **别用 `grep` 匹配自己的命令行**：`for p in /proc/*; do grep -q "<脚本名>" ...; done` 会匹配到**执行这条命令的 shell 自身**(argv 里就含那个串) ⇒ 把自己 kill 掉(exit -15)。
  修法①判据写拼接串(`P="vl_safety""_monitor.py"`)；修法②把循环放进**独立脚本文件**再执行(它的 argv 只有路径)。
- **agent 会话里 `nohup/setsid ... &` 起的常驻进程会随会话清理一起死**(终端工具也直接拒这类包装)：要用 `background=true` 交给 Hermes，或交给 **cron keepalive 每分钟探测+拉起**才算真脱离会话。
- **改完代码必须重启进程**：长驻守护跑的是内存里的旧代码 —— 本轮磁盘上改了 `timeout`/常量但没重启，误报又持续 2 小时。核验要对比 `ps` 启动时间 vs 文件 mtime。

## 支持文件
- `templates/unit-oneshot.service` — 开机一次性场景的 unit 骨架(含超时/台账注释)
- `templates/unit-daemon.service` — 常驻监听场景的 unit 骨架(PYTHONUNBUFFERED + Restart=always)
- `scripts/verify_service.sh` — 一键四件套核验
- `references/local-units.md` — 本机(4060 工位机)已落地的 unit 清单与各自口径
- `references/production-device-service-pattern.md` — 在别人的产线设备上放常驻服务: 硬约束/部署清单 + **看门狗指纹、独占设备去重、无人升级验收、版本取证**
- `references/self-exiting-service-chains.md` — 「自己会退」的常驻链(定时 `--seconds` · 跨 `docker exec` · 页面按钮打另一个端口): 必须托管 + 心跳可视 + 删除/清除按钮的真实语义 + 四步自检

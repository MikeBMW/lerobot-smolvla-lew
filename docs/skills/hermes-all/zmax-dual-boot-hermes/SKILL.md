---
name: zmax-dual-boot-hermes
description: "Use when U盘出差要带Hermes记忆或双系统数据架构(nvme0n1p5)维护。"
---

# Z-MAX U盘/E盘 双系统 + Hermes 随身镜像架构

老倪的机器 = U盘 LiveUSB(计算系统, / = /cow overlay, 持久层 sda2 casper-rw) + E盘 nvme0n1p5(label=ubuntu-e, 数据家)。**Hermes 大脑(~/.hermes, 2.3G, 程序 hermes-agent 也在其中)物理住在 E盘**;U盘启动时由 systemd 把 E盘目录 bind 进 U盘系统 → 两端天然同一份记忆, 不需要"同步"。飞书 gateway 也读同一份 ~/.hermes, 跟"从哪块盘开机"无关。

本技能覆盖: bind 机制、**U盘随身镜像**(U盘离开 E盘也能带全记忆工作)、离家/回家自动切换、排障。E盘克隆迁移本身见用户自有技能 e-drive-ubuntu-clone(建议 `hermes curator adopt` 后并入本技能体系)。

## 使用模型(老倪的日常)
- 在家(本机, E盘在): E盘主模式, U盘读写直通 E盘
- 出差(插别的机器): 开机检测无正牌 E盘 → 自动 bind /home/ubuntu/.hermes-mirror 到 ~/.hermes → 静静记忆/技能/程序/飞书凭证全在
- 回家: 开机先回灌(出差期间镜像里新记忆/技能 → E盘), 再切 E盘主模式

## 组件清单(2026-09-06 部署, 全部实测)
| 组件 | 路径 | 作用 |
|---|---|---|
| 随身镜像 | /home/ubuntu/.hermes-mirror | U盘 casper-rw 层 .hermes 全量镜像(~2.3G, **平铺结构**: mirror/config.yaml, 无嵌套 .hermes/) |
| 主挂载脚本 v2 | /usr/local/bin/zmax-data-mount.sh | label 校验 → 挂 E盘 → 回家回灌 → bind → 后台同步镜像 |
| 主挂载服务 | /etc/systemd/system/zmax-data-mount.service | ConditionPathExists=/dev/nvme0n1p5, U盘系统开机跑 |
| 镜像同步脚本 | /usr/local/bin/zmax-hermes-mirror.sh | E盘→mirror 全量 rsync, 只在主模式跑 |
| 兜底脚本+服务 | /usr/local/bin/zmax-hermes-fallback.sh + /etc/systemd/system/zmax-hermes-fallback.service | 无正牌 E盘时 bind mirror→~/.hermes(离家模式) |
| 定时同步 | zmax-hermes-mirror.timer | OnBootSec=15min + OnUnitActiveSec=6h + Persistent |
| gateway 顺序 | hermes-gateway.service 已加 `After=zmax-data-mount.service zmax-hermes-fallback.service` | 防空壳 .hermes 抢跑 |

详细部署记录/脚本逻辑/验证步骤: references/portable-mirror-deploy.md

## 核心铁律与坑
1. **身份校验必须看 label, 不能只看设备存在**: 陌生笔记本也有 nvme0n1p5, 原脚本会误挂别人硬盘。用 `blkid -s LABEL -o value $DEV` == "ubuntu-e" 才动; 不匹配 exit 3, 交给 fallback 走 U盘镜像
2. **镜像必须含 hermes-agent 程序本体**(在 ~/.hermes/hermes-agent 里, 1.2G): 离家时程序、gateway 都从镜像跑, 缺了 = 没有静静
3. **mirror 是平铺结构**: rsync $SRC/ → $MIRROR/。回灌/fallback 脚本若写 $MIRROR/.hermes/... 会误判(本会话实测踩过, 已修正)
4. **主/离家模式判定用 findmnt 源**: `mountpoint -q ~/.hermes` 区分不了(mirror bind 后也是挂载点);要 `findmnt -no SOURCE ~/.hermes` 含 nvme0n1p5 才是主模式
5. **镜像排除运行态**: gateway.pid/sock/lock、*.log、*.lock、*.pid、logs/ cache/ image_cache/ audio_cache/ tmp/ .cache/; 用 .syncing 文件防开机+定时并发
6. **回家回灌只 -u 不删**, 范围 = 文本类 memories/ skills/ config.yaml/ auth.json/ cron/ hooks/ feishu_seen_message_ids.json(会话库 state.db 以 E盘为准不回灌)
7. **memories 文件名是大写**: MEMORY.md / USER.md(查完整性别用小写猜)
8. 验证: 主脚本幂等可重跑(已 bind 的目录 mountpoint 检查跳过); fallback 主模式时 exit 0 不干扰

## 待真机验证
离家分支无法在开机状态安全模拟(umount bind 会切断当前会话的 .hermes)。验证法: 老倪关机拔 E盘(或插别的机器)只插 U盘开机 → 问"暗号是多少"→ 答 7。新改动后重启务必先验证此点再交付。

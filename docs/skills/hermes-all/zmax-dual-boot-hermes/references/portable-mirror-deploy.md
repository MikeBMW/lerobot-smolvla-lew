# U盘随身镜像部署记录 (2026-09-06, 全部实测)

## 背景
老倪需求: "以后 U盘需要带着, 可能插到别的机器上, U盘上需要有备份记忆"。
改造前: ~/.hermes(静静全部, 含 hermes-agent 程序 1.2G + state.db 452M + skills 36M)物理在 E盘 nvme0n1p5,
U盘 Live 系统靠 systemd bind 借用。U盘离开 E盘 → 失忆。
改造后: U盘持久层有全量镜像 + 三服务自动切换, 离家插任何机器静静记忆完整。

## 系统事实(排障先核对)
- U盘系统根: / = /cow overlay (upper 在 sda2 casper-rw, ext3 100G); /cdrom = sda1
- E盘: /dev/nvme0n1p5 ext4, label=**ubuntu-e**, 挂 /mnt/zdata; bind 目标 = .hermes/lerobot-smolvla-lew/Documents/Desktop/Downloads
- 非 bind 的 /home/ubuntu/* 写入落在 casper-rw, 随 U盘走、重启保留(故 mirror 目录放这里)
- .hermes 总 2.3G; hermes-gateway 和 CLI 都从 ~/.hermes/hermes-agent/venv 启动 → 镜像必须含程序
- bind 挂载由脚本执行, /etc/systemd/system/ 下**没有** .mount 单元文件(systemctl list 里的 home-ubuntu-*.mount 是运行时视图, 别去找文件)

## 脚本逻辑
### /usr/local/bin/zmax-data-mount.sh (v2 主挂载)
1. root 源非 overlay(E盘系统启动)→ 数据本盘 exit 0
2. 身份校验: `blkid -s LABEL -o value /dev/nvme0n1p5` != "ubuntu-e" → exit 3(不挂不碰, 交 fallback)
3. 挂 E盘到 /mnt/zdata → E盘无 .hermes 时首次 rsync 迁移
4. **回家回灌**(bind 前): mirror 有 config.yaml 时, 对 memories skills config.yaml auth.json cron hooks feishu_seen_message_ids.json 逐个 `rsync -au mirror/$sub EDATA/.hermes/`
5. bind 五个目录(逐个 `mountpoint -q` 判重, 幂等)
6. nohup 后台跑 mirror 同步

### /usr/local/bin/zmax-hermes-mirror.sh (E盘→镜像)
- 主模式判定: `findmnt -no SOURCE /home/ubuntu/.hermes` 含 nvme0n1p5 才同步(mountpoint -q 不可用, 离家时 mirror bind 后也是挂载点)
- 防并发: $MIRROR/.syncing 标记存在即 skip
- rsync -aAX --delete, 排除: gateway.pid/sock/lock、gateway-starts.log、*.log、*.lock、*.pid、logs/ cache/ image_cache/ audio_cache/ tmp/ .cache/
- 源完整判据: -d $SRC/hermes-agent

### /usr/local/bin/zmax-hermes-fallback.sh (离家兜底, 顺序判定)
1. `mountpoint -q ~/.hermes` → 主模式已生效, exit 0
2. 正牌 E盘存在(label 匹配)→ 交主模式, exit 0(防 zmax-data-mount 时序失败)
3. 否则 `mount --bind /home/ubuntu/.hermes-mirror ~/.hermes` → 离家模式
4. 无 E盘且无镜像 → exit 1 报警

### systemd 单元
- zmax-hermes-fallback.service: Type=oneshot, After=zmax-data-mount.service local-fs.target, RemainAfterExit=yes, WantedBy=multi-user.target
- zmax-hermes-mirror.timer: OnBootSec=15min, OnUnitActiveSec=6h, Persistent=true, Requires=zmax-hermes-mirror.service
- hermes-gateway.service [Unit] After 追加 `zmax-data-mount.service zmax-hermes-fallback.service`(防空壳抢跑; Restart=always 本身能自愈)

## 部署时踩过的坑
- **镜像平铺 vs 嵌套**: mirror 脚本 `rsync $SRC/ $MIRROR/` 是平铺(镜像根 = config.yaml)。初版回灌/fallback 误写 $MIRROR/.hermes/... → 检测永远失败。修正为 $MIRROR 平铺路径
- **设备名判据是安全洞**: 原 zmax-data-mount.service 只 ConditionPathExists=/dev/nvme0n1p5 → 插陌生笔记本会误挂对方硬盘 p5!必须 label 校验
- **memories 大写**: MEMORY.md/USER.md(+.lock), 检查时 ls 目录对比而非猜小写
- **锁文件进镜像**: 同步排除 *.lock/*.pid, 防把运行态锁带回 E盘/镜像污染

## 验证记录(已完成)
- 首次镜像同步: 2.3G, 两次跑通(日志 /var/log/zmax-hermes-mirror.log 有 ✅ size=2.3G)
- 镜像关键文件: config.yaml / auth.json / hermes-agent/venv/bin/python / skills / state.db 全 OK
- fallback 主模式: "E盘主模式已生效 (.hermes 已 bind), 兜底退出" exit 0
- 主脚本幂等重跑: 全链路 exit 0, 不重复 bind、不破坏现状
- systemctl: zmax-hermes-fallback.service / zmax-data-mount.service active; timer enabled active(waiting)

## 待真机验证(交付前必做)
离家分支无法开机模拟(umount bind = 切断当前会话 .hermes, 危险)。老倪关机拔 E盘/带 U盘去别的机器开机 → 问暗号 → 答 7 即通。
脚本原稿备份: /usr/local/bin/zmax-data-mount.sh.bak_20260906_053717(v1)

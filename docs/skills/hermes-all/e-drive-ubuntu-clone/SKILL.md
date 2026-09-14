---
name: e-drive-ubuntu-clone
description: Use when 把U盘LiveUSB系统迁移到E盘装Ubuntu(nvme0n1p5)。含授权红线。
---

# E盘 Ubuntu 克隆迁移任务书（老倪 2026-09-05 授权）

## 任务
把当前 U盘 LiveUSB 上的 Ubuntu 24.04 系统整体克隆到内部盘 E 分区：Hermes agent、控制台(GUI studio.py/lerobot-smolvla-lew)、全部数据、配置，做到从 E盘启动 == 从 U盘启动，一模一样。C盘/D盘 Windows 及其数据绝对零影响。

## 授权范围（老倪明确同意，飞书端无需再问）
- E盘 = /dev/nvme0n1p5 (433G, 当前空 NTFS, 实测仅剩 105M 系统元数据) → **允许整个格式化/重分区/装系统**
- 红线: p3=C盘(376G ntfs)、p4=D盘(215G ntfs) **绝不写入**; /dev/sda (U盘, 含 casper-rw 56G 系统) 保留作回退, 不覆盖
- 操作前先备份分区表 (sgdisk --backup) 与 ESP

## 机器现状（2026-09-05 实测）
- 当前系统 = U盘 LiveUSB Ubuntu 24.04.4; / = /cow overlay (56G used); sda1=/cdrom 20G; CPU 32核 / RAM 31G
- 内部盘 /dev/nvme0n1 = 1024G GPT (UMIS 1T):
  - p1 0.31G fat32 ESP ← Windows 引导在此 (\EFI\Microsoft\bootmgfw.efi), Boot0002
  - p2 0.02G msftres; p3 376G ntfs=C; p4 215G ntfs=D; p5 433G ntfs=E
- UEFI 启动; BootOrder: 0002(Windows), 2001(USB), 0000(Linpus=USB grub)
- 迁移量: / 56G; /home 38G(lerobot-smolvla-lew 11G + lerobot-venv 7.6G + wheels-cu128 4.7G + snap 2.4G + hermes 备份zip若干); /snap 12G; /usr 8.1G; /var 5.7G; /opt 2.1G

## 执行方案
1. **安全准备**: `sgdisk --backup=/root/nvme-gpt.bak /dev/nvme0n1`; 备份分区表
2. **目标盘准备**（默认 B, 不动分区表最安全）:
   - A 方案(8/22 旧案, 隔离最彻底): 重分区 p5 → 1G fat32(ESP) + 剩余 ext4
   - **B 方案(推荐)**: `sgdisk -t 5:8300 /dev/nvme0n1` 改类型码 + `mkfs.ext4 /dev/nvme0n1p5`; grub 的 EFI 文件装入 p1 ESP 的 \EFI\ubuntu\ (只新增目录, 绝不碰 \EFI\Microsoft)
3. **克隆**: 挂载 p5 → `rsync -aAXHx / <p5挂载点>/` 排除 /proc /sys /dev /run /tmp /media /mnt /cdrom /rofs /cow (live 层)
4. **落地配置**: chroot 改 /etc/fstab(用 p5 ext4 UUID); 去除 casper/live 引导参数; **先恢复 initrd 生成链**(见坑: 从同版本 initramfs-tools deb 恢复真版 update-initramfs + mkinitramfs 到 /usr/sbin/, 否则 update-initramfs 静默失败) → update-initramfs -c -k <ver> → **验证 initrd 实体存在** → grub-install --efi-directory=<p1挂载点> --bootloader-id=ubuntu → update-grub → **验证 grub.cfg menuentry 含 initrd 行**
5. **引导项**: efibootmgr 新建 "Ubuntu E盘" → \EFI\ubuntu\grubx64.efi; BootOrder 置前(保留 Windows 0002)
6. **验证**: 重启从 E盘启动; 核对 Hermes/控制台/数据/GPU(CUDA) 齐全; C/D 盘抽查文件校验一致

## 坑（8/22 教训）
- **casper 包残留 = initrd 污染(2026-09-05 E盘首启失败根因)**: rsync 克隆把 casper 包整套带进 E盘(hook=/usr/share/initramfs-tools/hooks/casper + conf.d/casperize.conf + default-layer.conf + scripts/casper*)。即使 initrd 实体存在、模块齐全、grub root=UUID 正确,生成的 initrd 仍混装 casper 脚本(casper-premount 注册进 init-premount)→ E盘启动 casper 先找 live 介质失败 → 报 "unable to find a medium containing a live file system"(不是 kernel panic!)。**修复**: chroot `dpkg -P casper`(无依赖者可干净 purge)+ rm conf.d 残留 → 重新 update-initramfs。**验证铁律⑤**: unmkinitramfs 拆 initrd 后 `main/scripts` 不得出现 casper*(正确解剖法: unmkinitramfs 分段 early/early2/early3/main;zstd magic 定位/bs=512 skip 会解错,zstd rc=1 静默空输出误导)
- **LiveUSB 镜像禁用了 initrd 生成(2026-09-05 实测致命)**: `/usr/sbin/update-initramfs` 被 casper 换成 2 行 stub(只打印 "update-initramfs is disabled since running on read-only media"),`/usr/sbin/mkinitramfs` 被删。chroot 里跑 update-initramfs 必然静默失败 → 克隆系统 /boot 无 initrd.img-<ver> 实体(只有断 symlink) → E盘启动 kernel panic "VFS: unable to mount root fs on unknown-block(0,0)"(grub.cfg 也无 initrd 行,10_linux 检测不到 initrd 自动跳过)
  - **修复**: 宿主 `apt-get download initramfs-tools initramfs-tools-core`(版本须与 E盘 dpkg 一致,如 0.142ubuntu25.8) → `dpkg-deb -x` 解包 → 把真版 `usr/sbin/update-initramfs` + `usr/sbin/mkinitramfs` cp 进 E盘 /usr/sbin/ → bind /proc /sys /dev /run → `chroot <p5挂载> update-initramfs -c -k <ver>` → `chroot <p5挂载> update-grub`
  - **验证铁律**: ① /boot/initrd.img-<ver> 实体存在(85MB级) ② grub.cfg menuentry 有 `initrd /boot/initrd.img-<ver>` 行 ③ initrd 内含 nvme 驱动(6.17 内核模块是 `.ko.zst` 压缩格式,CONFIG_MODULE_COMPRESS_ZSTD;ext4 为内建无需 .ko,modules 目录空正常) ④ initrd 结构=microcode 未压缩段+usr 段+ zstd 主段(含 init/scripts/local),用 zstd -dc 解主段后 cpio -t 验证
- **mkfs/分区/grub 操作会被 Hermes 安全机制硬拦** → 老倪已预授权, 弹确认时点允许即可(不能手动操作, 须零人工则走安全审批流程)
- Live 系统不能对自己 dd; rsync 须 -x 防跨文件系统(会拷进 /rofs /cdrom squashfs)
- /dev/sda(U盘) 与 p1 的 \EFI\Microsoft 是禁区
- 中途失败回退: U盘仍在, BIOS 选 USB 启动即恢复原状
- grub-install 用 --no-nvram + 手动 efibootmgr 更可控, 避免 grub 擅自改 BootOrder

## 验收
唯一标准: E盘独立开机进 Ubuntu, 环境与 U盘一致(Hermes 技能/记忆/会话检索、控制台、训练环境), C/D 数据分毫未动。

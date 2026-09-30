# Live USB 救援 — 从 Windows Docker Desktop 备份恢复 (2026-08-22 实测)

## 场景
Windows 机器上有唯一的 Hermes 备份（D:\hermes-docker\workspace\hermes-backup\hermes_core_*.tar.gz = 完整 ~/.hermes 快照），但机器无法正常进系统 / 要在新机器继续。在旧机器上插 Ubuntu 启动 U 盘，只读挂载 NTFS，选择性解压。

## 识别环境（U 盘 Live 系统 vs Windows 盘）
- Live 系统特征：`/` 挂在 `/cow`（overlay），`/cdrom` 有挂载，`/rofs` 只读；磁盘标签 `UBUNTU 2024_0`（`ls /dev/disk/by-label/`，`casper-rw` = U 盘持久化层）
- `lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINT` 区分 U 盘（sda）与内置 NVMe
- NTFS 分区 = Windows 盘。认盘符看根目录内容（不要猜）：
  - C: `Windows/`、`hiberfil.sys`、`pagefile.sys`、`Program Files`、`$Recycle.Bin`
  - D（数据盘）: `hermes-docker/`、`产品/`、`xspace/` 等业务目录
  - E: `WSL/`（WSL ext4.vhdx 所在地）、`compact_vhdx.*` 日志

## 挂载（必须 -o ro！）
```bash
sudo mkdir -p /mnt/win3 /mnt/win4 /mnt/win5
sudo mount -o ro /dev/nvme0n1p3 /mnt/win3   # C
sudo mount -o ro /dev/nvme0n1p4 /mnt/win4   # D
sudo mount -o ro /dev/nvme0n1p5 /mnt/win5   # E
```
Windows 快速启动/休眠未关时，NTFS 读写挂载会损坏数据 → 一律只读，只做读取/拷贝。

### 需要写 NTFS 盘时（本次实测：存新备份进 D 盘）
`mount -o rw,remount` 对 fuseblk (ntfs-3g) **静默失败**——mount 显示仍是 ro，cp 报 "No such file or directory"（迷惑性极强，目录明明在）。必须：
```bash
sudo umount /mnt/win4
sudo mount -o rw /dev/nvme0n1p4 /mnt/win4   # 重挂 rw
cp <file> /mnt/win4/hermes-docker/workspace/hermes-backup/
sudo umount /mnt/win4                        # 写完立刻卸载，绝不留在 rw
```
注意备份目录路径在 `hermes-docker/workspace/hermes-backup/`，不在盘根。

## 找备份（D 盘 Docker Desktop 数据）
- `hermes-docker/workspace/hermes-backup/hermes_core_*.tar.gz` — 完整快照。包内布局：`.hermes/{config.yaml, .env, auth.json, cron/, skills/, memories/, state.db}`。**含密钥**，绝不进公开仓库/聊天。
- `hermes-docker/docker-data/wsl/disk/docker_data.vhdx`（25G）— 容器 WSL 发行版虚拟盘，需要时用 vhdx 工具提取，一般不需要。
- `workspace/` 下还有 create_gpu_container.bat 等启动脚本可参考。

## 选择性恢复（只同步技能）
```bash
cd ~ && mv .hermes/skills .hermes/skills.pre_usb_boot   # 先备份当前技能（可还原）
tar xzf <pkg> --wildcards '.hermes/skills/*'            # 只解技能
find ~/.hermes/skills -type f | wc -l                   # 验证
```
覆盖前对比版本：包内 `tar tvzf <pkg> | grep '<skill>/SKILL.md'` vs 本地 `ls -la`（mtime/大小），文件数 `tar tzf | grep -c` vs `find | wc -l`。备份更新才覆盖。

## 记忆对比坑（本次实测）
备份（08-19）的 MEMORY.md 可能比当前环境旧：备份仍写"ECS 密码 Nix19789 有效"，当前记忆已有"08-13 实测密码失效"的更新结论。**恢复记忆前必须 diff**（`tar xzf 到 /tmp` 后 diff，用后清理 `rm -rf /tmp/.hermes`），保留新事实。技能/代码可整目录覆盖，记忆要逐条合并——把已证伪的凭据当有效会直接坏事。

## 恢复后 bring-up（新机到全功能，用户 CICD 仪式）
用户标准流程：保存数据 → 小版本迭代 → 代码推送 → 系统保护 → 自检 → 可靠性维护。

1. **保存数据**: `hermes backup -o ~/hermes_core_usb_$(date +%Y%m%d_%H%M).zip` — 实测 228M 完整包（skills/sessions/config）。恢复 = `hermes import <zip>`。拷进 D 盘备份目录（见上面 rw 挂载）。
2. **小版本迭代**: `hermes update --check` 确认落后 → `hermes update --yes`。实测 v0.19.0 → v0.20.5：git pull + 依赖重装 + Web UI 重建 + 33 个内置技能同步。**用户技能（zmax-console 等）不被覆盖**，更新后验证 `hermes --version` + 技能文件还在。
3. **代码推送**: U 盘新机无用户仓库时无 push 目标——hermes-agent 是 NousResearch 官方仓库（只读），只做 pull。如实汇报缺口，别虚构推送。**用户要克隆项目仓库时**（本次：lerobot-smolvla-lew 从 GitHub 同步）：镜像 clone + pushInsteadOf 双通道（fetch 走镜像、push 走官方，镜像只读不能直接 push）：
   ```bash
   git clone https://ghfast.top/https://github.com/MikeBMW/lerobot-smolvla-lew.git
   cd lerobot-smolvla-lew
   git config url."https://github.com/".pushInsteadOf "https://ghfast.top/https://github.com/"
   ```
4. **系统保护**: `sudo $(which hermes) gateway install --system`（sudo 丢 PATH，`sudo hermes` 直接 command not found）。实测：安装 + enable + 立即启动 hermes-gateway systemd 服务；live-USB casper-rw 持久层下重启可保留。
5. **自检**: `hermes doctor`（Python/SQLite/SSL/config 版本）+ `hermes status`（API key）+ `hermes gateway status`。
6. **可靠性维护**: `hermes cron status` — 刚启动时 ticker 可能报 STALLED + 10 小时前心跳（启动前旧状态残留），等 15-60s 再查，出现 "Ticker heartbeat: Xs ago" + "N active job(s)" 即恢复。确认 `~/.hermes/scripts/` 下 watchdog/链路巡检/磁盘红线脚本都在。
7. **桌面补充（中文输入法）**: `apt install ibus-pinyin` → `ibus engine libpinyin` → **gsettings 固化**（`preload-engines=['libpinyin']` + Ctrl+Space 热键）+ 环境变量写 ~/.bashrc。⚠️ **hermes update 会把引擎重置回英文**（xkb:us::eng）——用户问"中文输入法呢"时先查 `ibus engine`（别只看 pgrep），重设引擎 + 确认 gsettings preload 列表。

## 完成清单
- [ ] 技能同步 + 对比验证（文件数 + SKILL.md 版本）
- [ ] 记忆：diff 后决定，不自动覆盖
- [ ] config/auth/cron：不动（当前环境自有一套，能跑就说明是好的；用户只要求同步技能就只做技能）
- [ ] 清理临时解压目录
- [ ] bring-up：hermes backup → update → gateway systemd → doctor/status → cron 心跳验证

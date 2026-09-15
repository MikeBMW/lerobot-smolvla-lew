# 双显卡(Optimus)笔记本 外接屏不亮 / 显示闪烁 — 真实根因与处置 (2026-09-15 实测修订)

> 本文件推翻了 SKILL.md 里 2026-08-25 那条 "modeset=0 根治 gem 错误/闪屏" 的结论。
> 那次是**误判**: 关掉 KMS 只压住了症状, 代价是把外接显示器永久废掉 (核显根本没有那条通路)。
> 真实根因是 **Xorg 的 NVIDIA 显示驱动 (DDX) 没装**。

## 0. 实测环境
Lenovo ThinkBook 16p G5 IRX (21N5) · Intel RPL-S 核显 + RTX 4060 Laptop (NVIDIA 580.126.09)
Ubuntu 24.04.4 (E 盘 p5 原生) · 内核 6.17.0-14-generic · X11 会话 (gdm autologin)
现象: Windows 下 HDMI 外接屏正常; Ubuntu 下 `xrandr` 永远只有 eDP-1, 插拔 HDMI 毫无反应。

## 1. 先判: HDMI/DP 口挂在哪块 GPU 上 (决定一切)
```bash
for f in /sys/class/drm/card*/card*-*/status; do echo "$f = $(cat $f)"; done
for c in /sys/class/drm/card[0-9]*; do echo "$c -> $(basename $(readlink -f $c/device/driver))"; done
sudo dmesg | grep -iE "nvidia|hdmi" | tail -20
```
- 只有 `card1-eDP-1`(i915), 一个 `HDMI-A-*` 都没有, 且 dmesg 里独显声卡 `0000:01:00.1` 挂着
  `HDA NVidia HDMI/DP,pcm=3/7/8/9` → **口在 dGPU 上**(本机就是)。此时 modeset=0 = 外接屏永久失效。
- 若 i915 侧已列出 `card1-HDMI-A-1`(哪怕 disconnected) → 口在核显上, 与 nvidia 无关。
- **"Windows 能用" 不是驱动没坏的证据**: Win 驱动始终开 KMS。
- 本机 `boot_vga`: i915=1, nvidia=0 → 内置屏始终走核显, 加装 DDX 不改内置屏通路。

## 2. 根因 (两条, 缺一不可)
1. `/etc/modprobe.d/nvidia-graphics-drivers-kms.conf` 里 `options nvidia_drm modeset=0`
   → nvidia-drm 不注册任何 connector, dGPU 的输出在内核里根本不存在 (card2 无 connector)。
2. **只装了计算栈, 没装显示驱动**: 2026-08-25 的安装命令是
   `apt-get install --no-install-recommends linux-modules-nvidia-580-<kernel> nvidia-utils-580
   libnvidia-gl-580 libnvidia-compute-580 libnvidia-decode-580 libnvidia-encode-580 libnvidia-cfg1-580`
   —— 缺 `xserver-xorg-video-nvidia-580`。全盘 `find / -name nvidia_drv.so` 为空。
   于是 card2 只能落到 modesetting 驱动, 而 dGPU 上没有 GL 驱动可用 → Mesa glamor 建不出 GEM
   → 老症状 `Failed to lookup gem object` / 显示器狂闪 / mutter 无法合成新窗口。
   **计算栈 ≠ 显示栈**, 这两套包必须分别确认。

## 3. 正确处置顺序
```bash
# ① 恢复 KMS (先备份旧文件!)
sudo cp -a /etc/modprobe.d/nvidia-graphics-drivers-kms.conf{,.modeset0.$(date +%Y%m%d)}
# 文件内容改为: options nvidia_drm modeset=1   (保留 NVreg_PreserveVideoMemoryAllocations=1 等其余行)

# ② 补齐 DDX, 版本必须 == 已冻结的内核模块版本
cat /sys/module/nvidia/version                     # 例 580.126.09
sudo apt-get install -y --no-install-recommends ./xserver-xorg-video-nvidia-580_580.126.09-0ubuntu0.24.04.1_amd64.deb
# 落地: /usr/lib/x86_64-linux-gnu/nvidia/xorg/nvidia_drv.so
#       /usr/share/X11/xorg.conf.d/10-nvidia.conf  (MatchDriver "nvidia-drm" → Driver "nvidia")
ldd /usr/lib/x86_64-linux-gnu/nvidia/xorg/nvidia_drv.so | grep "not found"   # 应为空

# ③ hold 住整套 nvidia (见 §4, 必做)
# ④ 重启 (modeset 是模块加载期只读参数; 运行中的 Xorg 持有 /dev/dri/card2 → rmmod EBUSY)
```
**为什么 DDX 版本必须 == 内核模块版本**: 本内核只有 126.09 的 Canonical 预编译签名模块
(`apt-cache policy linux-modules-nvidia-580-6.17.0-14-generic` 无更新候选), 用户态升到 173.02 就是
driver/library mismatch → nvidia-smi/CUDA/显示一起坏。**永远不要 `apt install nvidia-driver-XXX` 元包**
(它拉 dkms, SecureBoot 下要 MOK 注册, 见 SKILL.md 零人工安装节)。

## 4. 反向坑: unattended-upgrades 会自己把 GPU 拆了 (必堵)
本机 `APT::Periodic::Unattended-Upgrade "1"` 开着, 且 580.173.02 同时在 noble-**security** 里 →
半夜自动升级用户态, 内核模块跟不上 → 次日 GPU 全废。原子包 `linux-modules-nvidia-*` 不跟着升 (没有 173.02 候选)。
```bash
sudo apt-mark hold linux-modules-nvidia-580-$(uname -r) \
  libnvidia-cfg1-580 libnvidia-common-580 libnvidia-compute-580 \
  libnvidia-decode-580 libnvidia-encode-580 libnvidia-gl-580 \
  nvidia-kernel-common-580 nvidia-utils-580 xserver-xorg-video-nvidia-580
sudo apt-get -s dist-upgrade | grep -iE "^Inst (libnvidia|xserver-xorg-video-nvidia|nvidia-utils)"   # 应为空
```
以后升级 nvidia 必须**内核模块 + 用户态 + DDX 一起**: `apt-mark unhold` 全套再整包升。

## 5. 版本精确的 .deb 从哪来 (noble-updates 只有新版时)
Ubuntu 的 release pocket 会把被 -updates 取代的包从线上撤掉, `apt-cache policy` 只会显示 cdrom 源有旧版 →
**旧版只在安装 ISO 的 pool 里**。ISO 常常就躺在 Windows 分区 (本机: `Users/<user>/Downloads/ubuntu-24.04.4-desktop-amd64.iso`):
```bash
sudo mkdir -p /mnt/winp3 /mnt/iso
sudo mount -o ro /dev/nvme0n1p3 /mnt/winp3                       # 只读挂 NTFS, 不动 Windows
sudo find /mnt/winp3 -maxdepth 4 -iname "*.iso"
sudo mount -o loop,ro /mnt/winp3/.../ubuntu-24.04.4-desktop-amd64.iso /mnt/iso
sudo find /mnt/iso -iname "xserver-xorg-video-nvidia-*deb"        # → /mnt/iso/pool/restricted/n/...
sudo apt-get install -y --no-install-recommends <deb>             # 先 apt-get -s 模拟, 确认只新增 1 个包
# 用完: umount /mnt/iso; umount /mnt/winp3   (p3 busy 是因为 loop 挂在它上面, 顺反了)
```
`launchpad/archive pool` 里旧版常已 404 (实测 126.09 的 24.04 版 DDX 就没了), 别浪费时间去 curl pool;
NVIDIA 官方 `.run` 里也有 nvidia_drv.so 但 396MB 且实测 ~1MB/s, ISO 优先。
备一份 deb 到 `~/pkg/`, 换内核/重装后可直接复用。

## 6. 重启后验证 (期望值)
```bash
ls /sys/class/drm/                                  # 新增 card2-HDMI-A-1; status = connected
xrandr --query | grep -E "^[A-Za-z]+-[0-9]"         # eDP-1 有模式 + HDMI-A-1 connected <mode>+<内屏宽>+0
xrandr --listproviders                              # 出现 NVIDIA-0 provider
grep -iE "nvidia|HDMI|modeset" /var/log/Xorg.0.log  # nvidia 驱动加载 + connector
```
- **连接器出现但屏不亮**: GNOME 偶尔不自动做 reverse PRIME, 手工点亮 (**不用重启**):
  `xrandr --setprovideroutputsource <nvidia_provider> <intel_provider>`
  → `xrandr --output HDMI-A-1 --auto --right-of eDP-1`
  一体化脚本: `scripts/dual_screen_setup.sh` (只在 "已连线但未点亮" 时动手, 日志落 ~/reports/)。
- **仍闪屏**: 再关细粒度省电 `options nvidia "NVreg_DynamicPowerManagement=0x00"` + 重启
  (历史 gem 报错的另一诱因; `lib/modprobe.d/nvidia-runtimepm.conf` 默认 0x02)。
- **彻底回滚** (外接屏会再次失效, 内置屏必恢复): `options nvidia_drm modeset=0` + `sudo update-initramfs -u` + 重启;
  可选 `apt remove xserver-xorg-video-nvidia-580`。图形界面起不来时 Ctrl+Alt+F3 进 tty 执行。

## 7. 交付给用户的物 (老倪要"证据/根因/回滚")
`~/DUAL_SCREEN_FIX_<date>.md`: 现象 · 两条根因+证据 · 改动清单(含备份路径) · 生效方式(重启) ·
验证命令+期望输出 · 三级回滚 · 明确声明 "未碰 CUDA (版本一字未变, nvidia-smi 仍报 X)"。
现场先自己把能验的都验掉: `nvidia-smi` 版本一致、`boot_vga` 仍 i915=1、`modinfo nvidia` 版本、hold 生效
(`apt-get -s dist-upgrade` 无 nvidia 条目)、磁盘/网关未受影响。

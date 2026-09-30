# Ubuntu 双屏(外接 HDMI)修复记录 — 2026-09-15

机型: Lenovo ThinkBook 16p G5 IRX (21N5), iGPU Intel RPL-S + dGPU RTX 4060 Laptop (NVIDIA 580.126.09)
系统: E 盘 nvme0n1p5 原生 Ubuntu 24.04.4, 内核 6.17.0-14-generic, 会话 X11 (GDM autologin)
现象: Windows 下外接 HDMI 正常; Ubuntu 下永远没有第二块屏 (xrandr 只有 eDP-1)

---

## 一、根因 (两条, 缺一不可)

### 1. dGPU 的 KMS 被关掉了 → 外接屏的内核接口根本不存在
`/etc/modprobe.d/nvidia-graphics-drivers-kms.conf` 里 2026-08-25 写死 `options nvidia_drm modeset=0`
(当时的注释: 规避 nvidia_drm gem 报错导致 mutter 合成失败/显示器狂闪, "显示纯走 Intel i915 eDP-1")。
mode 0 时 nvidia-drm 不注册任何 connector, 于是:

    /sys/class/drm/ 下长期只有 card1 (i915) 的 card1-eDP-1,
    card2 (nvidia) 一个 connector 都没有 → Xorg 无从点亮任何 dGPU 输出。

**本机 HDMI 口物理上接在 dGPU 上** — 证据: i915 只暴露 eDP-1 一个输出(若 HDMI 走 iGPU 会看到
card1-HDMI-A-1), dmesg 里 NVIDIA 声卡 (01:00.1) 挂出 HDMI/DP pcm=3/7/8/9 四条输出,
pci 0000:01:00.0/drm/ 只有 card2/renderD129。Windows 永远能用是因为 Win 驱动始终开着 KMS。

### 2. Xorg 的 NVIDIA 显示驱动 (DDX) 从来没装 → 就算开了 KMS 也没人驱动那块屏
`apt-get install --no-install-recommends linux-modules-nvidia-580-... nvidia-utils-580
libnvidia-gl-580 libnvidia-compute-580 libnvidia-decode-580 libnvidia-encode-580 libnvidia-cfg1-580`
(2026-08-25 那次安装) 只装了 **计算栈**: 没有 xserver-xorg-video-nvidia-580,
所以 /usr/lib/xorg/modules/drivers 与 /usr/lib/x86_64-linux-gnu/nvidia/xorg 里都没有 nvidia_drv.so。
Xorg 只能把 card2 当普通 KMS 设备交给 modesetting 驱动, 而 card2 上的 GL 无驱动可用 →
这正是当年的 "nvidia_drm gem 错误 + mutter 无法合成新窗口 + 显示器狂闪" (Mesa glamor 建不出 GEM)。
当时把 modeset 关掉算是把症状"压住"了, 代价是外接屏永久失效。

---

## 二、本次改动 (3 项, 全部可回滚)

1. **KMS 恢复**
   - `/etc/modprobe.d/nvidia-graphics-drivers-kms.conf` → `options nvidia_drm modeset=1`
   - 旧文件备份: `/etc/modprobe.d/nvidia-graphics-drivers-kms.conf.modeset0.20260915`
     (更早还有 `.bak.20260825`)
2. **补齐 Xorg NVIDIA 显示驱动 (版本必须 580.126.09)**
   - 安装 `xserver-xorg-video-nvidia-580 580.126.09-0ubuntu0.24.04.1` (amd64)
   - deb 来源: Windows 分区里的安装 ISO
     `/mnt/winp3/Users/xspace/Downloads/ubuntu-24.04.4-desktop-amd64.iso`
     → `pool/restricted/n/nvidia-graphics-drivers-580/` 里的原厂 deb (挂载只读, 装完已卸载)
   - deb 已备份: `/home/ubuntu/pkg/xserver-xorg-video-nvidia-580_580.126.09-0ubuntu0.24.04.1_amd64.deb`
   - 落地文件: `/usr/lib/x86_64-linux-gnu/nvidia/xorg/nvidia_drv.so`
     + `/usr/share/X11/xorg.conf.d/10-nvidia.conf` (MatchDriver "nvidia-drm" → Driver "nvidia")
   - **为什么不用 apt 里的 580.173.02**: 本内核 6.17.0-14 只有 126.09 的预编译内核模块
     (linux-modules-nvidia-580-6.17.0-14-generic 无更新候选), 用户态升到 173.02 会
     driver/library 版本错配 → nvidia-smi/CUDA/显示一起坏。必须同版本。
3. **hold 住这套 126.09 的 nvidia 包**, 防止 unattended-upgrades 半夜把用户态升到 173.02 拆掉 GPU:
   linux-modules-nvidia-580-6.17.0-14-generic / libnvidia-{cfg1,common,compute,decode,encode,gl}-580 /
   nvidia-kernel-common-580 / nvidia-utils-580 / xserver-xorg-video-nvidia-580
   (未改动的隐患: 这机器本来就有这个"自动升级自毁"风险, 与双屏无关, 顺手一起堵了)
   → 以后要升级 nvidia, 必须**内核模块+用户态一起**升: `sudo apt-mark unhold ...` 再整包升。

---

## 三、生效方式: **重启** (nvidia_drm 的 modeset 是模块加载期只读参数, 无法热改;
且运行中的 Xorg 已持有 /dev/dri/card2, 不能 rmmod)

    sudo reboot

## 四、重启后验证 (期望结果)

    bash ~/bin/dual_screen_setup.sh          # 一键诊断+点亮 (日志落 ~/reports/)
    xrandr --query | grep -E "^[A-Za-z]+-[0-9]"
    # 期望: eDP-1 connected 3200x2000 ...  +  HDMI-A-1 connected 1920x1080+eDP宽度+0 ...  (两行都有分辨率)
    xrandr --listproviders                    # 期望: 出现 NVIDIA-0 provider
    ls /sys/class/drm/                        # 期望: 新增 card2-HDMI-A-1
    grep -iE "nvidia|HDMI|modeset" /var/log/Xorg.0.log | head -30

若连接器出现但屏幕不亮 → 跑一次 `bash ~/bin/dual_screen_setup.sh`
(它做 reverse PRIME: `xrandr --setprovideroutputsource <nvidia> <intel>` 再 `--output HDMI-A-1 --auto --right-of eDP-1`,
**不需要再重启**)。GNOME 通常自己会做这一步; 脚本只在"已连线但未点亮"时才动手。

## 五、回滚 (任一, 都需重启)

**A. 只要不回退(推荐, 先试):** 屏幕若不亮/闪烁, 先在终端跑 `bash ~/bin/dual_screen_setup.sh`,
或把 dGPU 的细粒度运行时省电关掉再看 (历史 gem 报错的另一个常见诱因):

    echo 'options nvidia "NVreg_DynamicPowerManagement=0x00"' | sudo tee /etc/modprobe.d/nvidia-runtimepm-off.conf
    sudo reboot

**B. 彻底退回改前状态 (外接屏会再次失效, 但内置屏/显示必恢复):**

    echo 'options nvidia_drm modeset=0' | sudo tee /etc/modprobe.d/nvidia-graphics-drivers-kms.conf
    sudo update-initramfs -u && sudo reboot

    彻底删掉新装的显示驱动(可选): sudo apt-mark unhold xserver-xorg-video-nvidia-580
                                    sudo apt remove xserver-xorg-video-nvidia-580

**C. 图形界面起不来时 (黑屏/卡在 tty):** Ctrl+Alt+F3 → 登录 → 执行上面的 B。

---
备注: 本次只动显示链路, 未碰 CUDA/训练环境 (内核模块与用户态库版本一字未变, nvidia-smi 仍报 580.126.09)。

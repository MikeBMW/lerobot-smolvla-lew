---
name: nvidia-gpu-driver-setup
description: Use when Ubuntu 装 NVIDIA 驱动或 nouveau 冲突加载失败。
---

# NVIDIA GPU 驱动安装 (Ubuntu / SecureBoot / Optimus 双显卡笔记本)

## 触发
- Ubuntu 装 NVIDIA 驱动, `nvidia-smi` 报 "couldn't communicate with the NVIDIA driver"
- SecureBoot 开启 + 要求零人工 (不能 MOK 注册 / 重启进 MOK 界面)
- 双显卡笔记本 (Intel 核显 + NVIDIA 独显, Optimus), nouveau 占着 GPU
- `modprobe nvidia` 报 `No such device` 或 dmesg `NVRM: GPU ... is already bound to nouveau.`

## 零人工安装 (SecureBoot, 2026-08-24 实测 RTX 4060 Max-Q 笔记本)
- **不要装 `nvidia-driver-XXX` 元包**: 它依赖 `nvidia-dkms-XXX`, DKMS 现场编译的模块未签名, SecureBoot 下要 MOK 注册(人工+密码+重启进 MOK 界面)。
- **正确**: 只装 Canonical 预编译签名模块 + 用户态库 (13 个包, 不拉 dkms):
  ```bash
  sudo apt-get install -y --no-install-recommends \
    linux-modules-nvidia-580-$(uname -r) \
    nvidia-utils-580 \
    libnvidia-gl-580 libnvidia-compute-580 libnvidia-decode-580 libnvidia-encode-580 libnvidia-cfg1-580
  ```
- **先 dry-run 确认不拉 dkms**: `apt-get install -s --no-install-recommends ... | grep -i dkms` 应为空, 输出 "N newly installed, 0 to remove"。
- **验签**: `modinfo nvidia | grep -E "signer|sig_id"` → 应见 `signer: Canonical Ltd. Kernel Module Signing` (Canonical 签名, SecureBoot 直接可用)。签名错会报 `Required key not available`(不是 No such device)。
- 签名模块包依赖 `linux-signatures-nvidia-<kernel>-generic`(提供签名), 与 dkms 编译模块是替代关系。内核模块在 `/lib/modules/$(uname -r)/kernel/nvidia-580/nvidia.ko`。
- LiveUSB 只读媒体: 装完提示 `update-initramfs is disabled since running on read-only media` 是预期, 无害。
- 版本对应: 驱动 580 → CUDA 12.8 → torch cu128 wheel (见 python-ml-env-mirrors)。

## ⚠️ 版本错配坑 (内核模块 vs 用户态库, 2026-08-24 实测)
- 症状: 重启后 `Kernel driver in use: nvidia`(nouveau 已 blacklist, nvidia 已接管), 内核模块 nvidia/nvidia_drm/nvidia_modeset 全加载, 但 `nvidia-smi` 报 "couldn't communicate with the NVIDIA driver", `/dev/nvidia*` 不存在, dmesg 见 `Direct firmware load for nvidia/XXX.XXX/gsp_ga10x.bin failed with error -2`。
- 根因: Ubuntu 预编译签名模块包 `linux-modules-nvidia-XXX-<kernel>` 的版本**冻结在内核发布时**(例 580.126.09), 而 `nvidia-utils-XXX` / `libnvidia-*` / `nvidia-firmware-XXX` 从 noble-updates 持续升到新版(例 580.173.02)。安装时若用户态装成 updates 最新版, 就与内核模块错配 → GSP 固件路径(nvidia/<内核版本>/gsp_*.bin)不存在 → 固件加载失败 → GPU 未真正初始化。
- **修复: 降级用户态匹配内核模块** (内核模块无法升, SecureBoot 下也不能上 DKMS):
  ```bash
  cat /sys/module/nvidia/version   # 拿到内核模块版本, 如 580.126.09
  sudo apt-get install -y --allow-downgrades --no-install-recommends \
    nvidia-utils-580=<版本>-0ubuntu0.24.04.1 \
    libnvidia-gl-580=<版本>-0ubuntu0.24.04.1 \
    libnvidia-compute-580=<版本>-0ubuntu0.24.04.1 \
    libnvidia-decode-580=<版本>-0ubuntu0.24.04.1 \
    libnvidia-encode-580=<版本>-0ubuntu0.24.04.1 \
    libnvidia-cfg1-580=<版本>-0ubuntu0.24.04.1 \
    libnvidia-common-580=<版本>-0ubuntu0.24.04.1 \
    nvidia-kernel-common-580=<版本>-0ubuntu0.24.04.1 \
    nvidia-firmware-580-<版本>    # 固件包名带完整版本号
  ```
  - 用户态旧版本只在 cdrom(LiveUSB ISO) 源有, noble-updates 已撤; 固件包在 updates 有更新的 .2 修订(同驱动版本, ABI 兼容)。
  - 降级后用 `ls /lib/firmware/nvidia/<版本>/gsp_ga10x.bin` 确认固件就位。
- **装完固件仍须重启**: 固件只在 nvidia 模块 probe 时加载。Optimus 笔记本 Xorg 会 mmap nvidia 的 DRM 设备(card2, `ls /sys/class/drm/` + `lsof /dev/dri/*` 可见), `nvidia_drm` use count=1, 运行时 rmmod 会 EBUSY 或崩 Xorg → 只能重启让内核重新 probe 加载固件。
- 安装命令务必先 dry-run 核对版本, 别让用户态被 `-y` 静默升到 updates 最新版。

## ⚠️ nouveau 冲突 (Optimus 笔记本, 最重要坑 — 别运行时切)
- 症状: `modprobe nvidia` 报 `No such device`; dmesg `NVRM: GPU 0000:01:00.0 is already bound to nouveau.`; `lspci -k` 显示 `Kernel driver in use: nouveau`。
- **运行时切换 nouveau→nvidia 会崩内核, 绝对不要做**:
  - 只 `modprobe -r nouveau` → nouveau 几乎立刻被内核重新 probe 拉回(没 blacklist)。
  - 先 `unbind` 再 `rmmod` → `nouveau_fence_emit` 触发 kernel oops(空指针), 连带崩 Xorg(`Xorg exited with irqs disabled`), `modprobe nvidia` 卡死在 D 状态 (`/proc/<pid>/wchan` = `__driver_attach`, probe GPU 卡死, kill -9 也杀不掉)。
- **唯一干净方案: blacklist nouveau + 重启**:
  ```bash
  printf 'blacklist nouveau\noptions nouveau modeset=0\n' | sudo tee /etc/modprobe.d/blacklist-nouveau.conf
  ```
  重启后 udev 按 nvidia 的 PCI alias (`pci:v000010DEd*sv*sd*bc03sc00i00*`, 匹配 VGA class 0300) 自动加载 nvidia, nouveau 被 blacklist 不抢。
- 显示走 Intel 核显(i915)的笔记本, 卸 nouveau 不影响显示; dmesg 里 nouveau "Cannot find any crtc or sizes" = 独显没接显示器, 可安全卸。

## ⚠️ nvidia_drm 显示闪烁 / gem 错误 (双显卡笔记本, modeset=0 根治, 2026-08-25 实测)
- 症状: 显示器狂闪、新窗口打不开(窗口 state=Iconic/IsUnMapped, `xdotool windowactivate` 无效)、GNOME 反复重绘; dmesg 反复刷 `nvidia_drm ... Failed to lookup gem object` + `nvidia-modeset: Unable to read EDID for display device DP-4`。
- 根因: nvidia_drm 默认 modeset=1(KMS 开), mutter 合成器用 nvidia(card2) 做显示合成时 gem 对象查找失败 → 反复重试 + EDID 重读 → 闪屏 + 窗口合不出。
- 根治: 关 nvidia KMS, 显示纯走 Intel 核显(i915/eDP-1), nvidia 只留 CUDA:
  ```bash
  printf '# 禁用 nvidia-drm KMS 根治显示器闪烁(gem错误)\noptions nvidia_drm modeset=0\n' | sudo tee /etc/modprobe.d/nvidia-graphics-drivers-kms.conf
  ```
  重启生效 (LiveUSB casper: /etc 在持久 overlay, 重启后配置仍有效)。
- 验证 (重启后):
  - `sudo cat /sys/module/nvidia_drm/parameters/modeset` → N (普通用户 cat 不了, 文件 -r-------- 需 sudo)
  - `sudo lsof /dev/dri/* | grep -E "mutter|gnome-shell"` → 全部挂 card1(Intel), 不再挂 card2(nvidia)
  - `sudo dmesg | grep -c "Failed to lookup gem object"` → 0
- 注意: modeset=0 后 nvidia-drm **仍加载**并注册 card2(用于 PRIME render offload), card2 不会消失, 这是预期; 消失的只是 mutter 对它的显示合成。EDID 警告若只剩 1-2 条一次性探测(DP-4 无显示器)属良性, 区别于之前的反复重读。

## 诊断路径 (modprobe nvidia 卡死/失败)
1. `lspci -nn | grep -iE "vga|3d|nvidia"` → 硬件在不在 (10de:xxxx 是 NVIDIA)。
2. `sudo lspci -k -s 01:00.0` → `Kernel driver in use: nouveau` = 被抢。
3. `sudo dmesg | grep -iE "NVRM|nvidia|nouveau" | tail` → "already bound to nouveau" / oops 栈。
4. `sudo cat /proc/<pid>/stack` + `cat /proc/<pid>/wchan` → modprobe 卡 `__driver_attach`(probe 卡死) 还是 `nv_pci_register_driver`。
5. `modinfo nvidia | grep signer` → 排除 SecureBoot 签名问题。

## Hermes 环境约束
- `reboot`/`shutdown` 被 Hermes 硬拦 (无条件阻止列表, 同 mkfs), agent 执行不了 → 需用户在终端外重启。
- PCI 热移除 `echo 1 > /sys/bus/pci/devices/0000:01:00.0/remove` + `rescan` 是危险操作会触发审批; 超时未确认会被禁重试。
- 两条都被堵时: 退回 CPU 训练。深度/双脑训练 CPU 可跑 (见 yolo-3d-perception-chain), 等下次重启后 GPU 自然接管再换 CUDA torch (wheel 下好即可, 见 python-ml-env-mirrors)。

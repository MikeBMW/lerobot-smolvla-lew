# LiveUSB 重启后 /dev/nvidia* 设备节点丢失 (2026-08-24 实测 RTX 4060 Max-Q)

## 症状 (与"版本错配坑"是两回事, 先区分再动手)
- 内核模块 nvidia / nvidia_drm / nvidia_modeset 全加载 (`lsmod | grep nvidia` 有)
- `/proc/driver/nvidia/version` 正常 (NVRM version 580.126.09)
- GPU 在 PCI (`lspci | grep -i nvidia` 可见 AD107M [RTX 4060 Max-Q])
- **版本匹配** (内核模块 = 用户态 = 580.126.09, 无错配)
- 但 `nvidia-smi` 报 "couldn't communicate with the NVIDIA driver"
- `ls /dev/nvidia*` → **一个都不存在** (No such file or directory)

判断口诀: `ls /dev/nvidia*` 空 + `lsmod | grep nvidia` 有 + `/proc/driver/nvidia/version` 有 → 是节点问题, 别再降级用户态/装固件(白折腾)。

## 根因
- LiveUSB(根文件系统是 overlay, `/` 挂成 /cow) 重启后 **/dev 是 tmpfs, 内容清空**。
- 正常 Ubuntu 靠 udev 规则 `/lib/udev/rules.d/71-nvidia.rules` 调 `/sbin/ub-device-create` 建节点, 规则挂在 `DEVPATH==/bus/pci/drivers/nvidia`。
- 但 nvidia 模块在启动早期 (systemd-modules-load 阶段) 就加载了, 那时 udev 还没跑这条规则 → 节点根本没建。
- `/sbin/ub-device-create` 工具本身是好的 (来自 nvidia-kernel-common-580 包), 手动跑退出码 0 且能建出全部节点(含 nvidia-uvm-tools)。

## 立即救急 (两选一)
```bash
# 方式 A: Ubuntu 自带工具, 按 /proc/devices 自动建全部 nvidia* 节点
sudo /sbin/ub-device-create

# 方式 B: 手动 mknod (主设备号从 /proc/devices 查: nvidia=195, nvidia-uvm=505)
sudo mknod -m 666 /dev/nvidiactl c 195 255
sudo mknod -m 666 /dev/nvidia0 c 195 0
sudo mknod -m 666 /dev/nvidia-modeset c 195 254
sudo mknod -m 666 /dev/nvidia-uvm c 505 0
```
跑完 `nvidia-smi` 立即通。

## 持久化 (零人工, 重启自愈)
写 systemd oneshot 服务, 不赌 udev 触发时序:

```ini
# /etc/systemd/system/nvidia-device-nodes.service
[Unit]
Description=Create NVIDIA device nodes (LiveUSB workaround: udev rule not firing on module load)
After=systemd-modules-load.service
Before=multi-user.target

[Service]
Type=oneshot
ExecStart=/sbin/ub-device-create
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

```bash
sudo cp nvidia-device-nodes.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable nvidia-device-nodes.service   # 重启自愈
systemctl is-enabled nvidia-device-nodes.service    # 验证 → enabled
```

## 验证 GPU 真可用 (不是假 is_available)
```bash
nvidia-smi   # 显示 RTX 4060, 驱动版本, 显存
gui-venv311/bin/python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
# 跑真 matmul, 确认 GPU 真在算:
gui-venv311/bin/python -c "import torch; x=torch.randn(1000,1000,device='cuda'); print((x@x).sum().item())"
```

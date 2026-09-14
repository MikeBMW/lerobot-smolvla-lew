# LiveUSB 重启后 nvidia_uvm 模块不加载 → torch 报 CUDA unknown error

与 `liveusb-device-node-loss.md`（节点全丢, nvidia-smi 都报错）是**两回事**，先区分再动手。

## 症状
- **`nvidia-smi` 完全正常**（能看到 GPU/驱动/显存/温度）。
- `ls /dev/nvidia*` 有 nvidia0 / nvidiactl / nvidia-modeset，但**缺 nvidia-uvm / nvidia-uvm-tools / nvidia-caps**。
- torch 层失败：
  ```
  torch 2.7.1+cu128
  CUDA initialization: CUDA unknown error ... Setting the available devices to be zero.
  cuda available: False
  device count: 1        # ← 矛盾: count 返回 1 但 available=False
  ```

**判断口诀**: `nvidia-smi` 正常 + `torch.cuda.is_available()=False` + 报 "CUDA unknown error" → 查 `lsmod | grep nvidia_uvm`。**空 = nvidia_uvm 模块没加载**（是模块问题，不是节点问题）。

## 根因
- LiveUSB 重启后 `nvidia_uvm` 内核模块不自动加载（`lsmod` 只有 nvidia / nvidia_modeset / nvidia_drm，缺 nvidia_uvm）。
- torch 的 CUDA 统一内存（UVM）依赖 `/dev/nvidia-uvm` 节点，该节点由 nvidia_uvm 模块注册。
- **关键坑**: `nvidia-device-nodes.service` 调的 `/sbin/ub-device-create` 在 nvidia_uvm **没加载**时只建 nvidia0/nvidiactl/nvidia-modeset 三个节点（`/proc/devices` 里没有 nvidia-uvm 条目，工具不会凭空建）→ 单靠它救不了 torch。ub-device-create "能建出全部节点含 nvidia-uvm-tools" 仅在 nvidia_uvm 已加载时成立。

## 修复
```bash
sudo modprobe nvidia_uvm                     # 先加载模块
UVM_MAJOR=$(awk '/nvidia-uvm$/{print $1}' /proc/devices)     # 实测 505
sudo mknod -m 666 /dev/nvidia-uvm c $UVM_MAJOR 0
sudo mknod -m 666 /dev/nvidia-uvm-tools c $UVM_MAJOR 1
CAPS_MAJOR=$(awk '/nvidia-caps$/{print $1}' /proc/devices)   # 实测 508
sudo mkdir -p /dev/nvidia-caps
sudo mknod -m 666 /dev/nvidia-caps/nvidia-cap1 c $CAPS_MAJOR 1
sudo mknod -m 666 /dev/nvidia-caps/nvidia-cap2 c $CAPS_MAJOR 2
```
跑完 `torch.cuda.is_available()` 立即 True。主设备号从 `/proc/devices` 动态读，别硬编码（不同驱动/内核版本会变）。

## 持久化 (补一个服务, 与 nvidia-device-nodes.service 并列)
```bash
sudo tee /etc/systemd/system/nvidia-uvm-nodes.service <<'EOF'
[Unit]
Description=Create NVIDIA UVM device nodes (CUDA fix)
After=nvidia-device-nodes.service
Before=multi-user.target
[Service]
Type=oneshot
ExecStart=/sbin/ub-nvidia-uvm-nodes
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
EOF
```
`/sbin/ub-nvidia-uvm-nodes` 脚本内容 = 上面"修复"那段（modprobe nvidia_uvm + awk 动态读主设备号 mknod）。`After=nvidia-device-nodes.service` 保证先建基础节点再补 uvm/caps。

## 验证
```bash
lsmod | grep nvidia_uvm                       # 模块已加载
ls -la /dev/nvidia-uvm /dev/nvidia-caps/      # 节点已建
gui-venv311/bin/python -c "import torch; print(torch.cuda.is_available())"   # True
```

## 关联
- 上层症状排查见 SKILL.md；节点全丢的姊妹坑见 `liveusb-device-node-loss.md`。
- 这次问题的实际触发场景：训练链路模型推理退化 → 视频生成卡死，根因一路追到 torch CUDA unknown error。教训：GPU 相关诡异失败（推理乱、0% 成功率）先查 `torch.cuda.is_available()` 和 `lsmod | grep nvidia_uvm`，再查上层逻辑。

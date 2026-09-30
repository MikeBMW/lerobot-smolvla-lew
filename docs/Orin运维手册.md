# Orin SSH 运维手册

> 最后更新: 2026-07-08

## 连接信息

| 项目 | 值 |
|------|-----|
| IP | 192.168.23.10 |
| 用户 | nvidia / root |
| ROS2 Domain | 23 |
| SSH 密钥 | `~/.ssh/id_ed25519` (ED25519) |

## 快速连接

```bash
# nvidia 用户（日常使用）
ssh nvidia@192.168.23.10

# root 用户（紧急维护）
ssh root@192.168.23.10

# ROS2 操作（带复用加速）
ssh -o ControlPath=/tmp/orin-ssh.sock nvidia@192.168.23.10 \
  "source /opt/ros/humble/setup.bash && ROS_DOMAIN_ID=23 ros2 topic list"
```

## 三层永固 SSH 方案

即使有人改了密码，密钥通道永远可用：

```
第1层: /home/nvidia/.ssh/authorized_keys   → chattr +i (不可变)
第2层: /root/.ssh/authorized_keys          → chattr +i (不可变)
第3层: /etc/ssh/global_authorized_keys     → chattr +i (不可变)
                                        ↘ sshd_config 已配置三重路径
```

所有三层文件被 `chattr +i` 锁定，只有 root 执行 `chattr -i` 才能修改/删除。

## 验证三层状态

```bash
ssh nvidia@192.168.23.10 "
  lsattr ~/.ssh/authorized_keys
  sudo lsattr /root/.ssh/authorized_keys
  sudo lsattr /etc/ssh/global_authorized_keys
"
# 正常输出: ----i---------e------- (每行都有 i 标志)
```

## 如果密钥失效了怎么办

### 情况1: 三层文件还在但密钥不对
**原因**: 有人修改了文件内容（但 chattr +i 保护应该阻止了）
**处理**: root 登录后检查

```bash
ssh root@192.168.23.10
cat /etc/ssh/global_authorized_keys   # 全局层最不可能被改
```

### 情况2: 密码被改了，但密钥还能用
**正常情况，无需处理**。密钥不受密码影响。

### 情况3: 需要更新密钥
```bash
# 先在Orin上解锁三层
ssh root@192.168.23.10
chattr -i /home/nvidia/.ssh/authorized_keys
chattr -i /root/.ssh/authorized_keys
chattr -i /etc/ssh/global_authorized_keys

# 更新密钥内容
echo "新的公钥" > /home/nvidia/.ssh/authorized_keys
echo "新的公钥" > /root/.ssh/authorized_keys
echo "新的公钥" > /etc/ssh/global_authorized_keys

# 重新锁死
chattr +i /home/nvidia/.ssh/authorized_keys
chattr +i /root/.ssh/authorized_keys
chattr +i /etc/ssh/global_authorized_keys
```

## 一键加固脚本

脚本位于 Orin: `/tmp/orin_ssh_harden.sh`

```bash
# 在Orin终端执行
sudo bash /tmp/orin_ssh_harden.sh
```

## 当前 SSH 配置

```
AuthorizedKeysFile .ssh/authorized_keys /etc/ssh/global_authorized_keys
PermitRootLogin yes
PasswordAuthentication yes
PubkeyAuthentication yes
```

## 故障排除

| 症状 | 原因 | 解决 |
|------|------|------|
| `Permission denied` | 密钥不对或文件被删 | 用 root 密钥登入检查三层 |
| `Connection refused` | sshd 没运行或IP不对 | 检查Orin是否开机、网络是否通 |
| `Host key verification failed` | WSL known_hosts 冲突 | `ssh-keygen -R 192.168.23.10` |
| ros2 topic list 为空 | daemon 挂了 | `pkill -9 -f ros2-daemon; ROS_DOMAIN_ID=23 ros2 daemon start` |
| ros2 命令找不到 | 没 source | `source /opt/ros/humble/setup.bash` |

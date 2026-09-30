# ⛔ 边缘机（Orin）零程序政策 — 覆盖本技能其余章节的部署写法

**2026-09-16 用户红线（原话，最高优先级）**
- 「**不要在orin上增加新程序。orin是生产设备，不能被干扰。你先只是转发orin的感知信号**」
- 「你不要在orin上安装新软件啊」

⇒ 本技能 SKILL.md 里「旁路（影子）运行器配方」那一节（scp 节点到 Orin + `@reboot` 守护 + crontab 自启
+ `ss_infer_service` 常驻）**默认全部作废**，只在用户明确批准时才用；
`references/ss-bypass-deploy.md` 里的同类写法同样降级为"历史实现参考"。
本次已把此前在 Orin 上部署的东西**全部回滚**（进程 0 / 自启 0 / 域内无 `zmax_ss` 话题 / 产线 8765 仍 `online`）。

## 默认形态：主机侧远程只读订阅（实测可跑，边缘零程序）
主机（无 ROS2 本地安装）用容器直接跨机订阅 Orin 的生产话题，边缘侧不跑任何桥：

```bash
sudo docker run -d --name <x>-remote-tap --network host \
  -e ROS_DOMAIN_ID=0 -e SS_OUT=/out -e SS_INFER_URL=http://127.0.0.1:8790/infer \
  -v /home/ubuntu/<repo>:/repo:ro -v /home/ubuntu/<out_dir>:/out \
  ros:humble-ros-base bash -c \
  "source /opt/ros/humble/setup.bash && exec python3 /repo/tools/<tap>.py --rate 10"
```

实测（25s 窗口，真值）：
| 话题 | 类型 | 频率 |
|---|---|---|
| `/robot/tcp_pose` | geometry_msgs/PoseStamped | **49.786 Hz**（frame=`base_link`，x=0.66391 y=−0.02925 z=0.29355） |
| `/real_joint_states` | sensor_msgs/JointState | **100.432 Hz** |
| `/robot/force_torque` | **同名双类型**（JointState + WrenchStamped） | 机器空闲时无发布者 |
| `/gripper_pos` | std_msgs/Float64 | 机器空闲时无发布者 |
| `/motion/active_states` | std_msgs/String | 机器空闲时无发布者 |

- 采集节点自证零发布：`enable_rosout=False` 关掉 `/rosout`，`self_publishers` 只剩 ROS 自带的 `/parameter_events`。
- 数据全落**主机**（`~/<项目>_remote/{state,proposal}_<日期>.jsonl` + `status.json`），Orin 上不留记录目录。
- 服务化用**主机** systemd：`Restart=always` + `Requires=docker.service` + `ExecStartPre=-/usr/bin/docker rm -f <name>`。
- 会**写回边缘机**的桥（`ss-bridge` 之类）在只转发形态下必须 `systemctl disable --now`。

## 回滚序列（已执行，留证据）
1. **先备份再删**（`tar czf /tmp/<name>_backup.tar.gz -C ~ …` → scp 回主机，本次 2.2MB）。
2. 停进程用**锚定模式**：`for p in $(pgrep -f "^python3 .*ss_"); do kill $p; done`
   ⚠️ **远程 `pkill -f "<名>"` 会杀掉自己这条 ssh 会话**：命令串任何位置出现明文进程名就中招
   （实测 `rm -f ~/.zmax/ss_shadow.log`、`tar … ss_edge.py` 这类**路径含进程名**也算），方括号 `[s]` 技巧救不了，
   症状是输出戛然而止 / exit 255 / -15。⇒ 用 `^python3` 锚定或先 pgrep 再按 PID kill，且别把含进程名的路径与 kill 写进同一条命令。
3. 清自启：先 `crontab -l | sed 's/^/OLD: /'` 留证，再 `crontab -l | grep -v <我加的每一行> > /tmp/ct.new && crontab /tmp/ct.new`。
4. 删文件：`~/.zmax/` 下的 start/daemon/log/link/shadow 与 `zmax_state_space/tools/ss_{edge,shadow}.py`。
5. **复核必须给证据**（不是"应该干净了"）：`pgrep -af "^python3 .*ss_"` 空 · `crontab -l` 空 ·
   `ros2 topic list | grep zmax_ss` = 0 · `curl 127.0.0.1:8765/health` = online · `ros2 node list | wc -l` = 18（产线自带）。

## 相关
- 完整配方/坑/诚实口径：`ros2-cross-machine-control-loop/references/edge-remote-readonly-tap.md`
- 本技能内：`references/ss-bypass-deploy.md`（Orin 侧部署细节，现为"需批准"的历史参考）。

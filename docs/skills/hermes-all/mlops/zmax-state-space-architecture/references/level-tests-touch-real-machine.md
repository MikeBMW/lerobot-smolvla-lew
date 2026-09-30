# 能力测试跑在现场机上会动真机（真实踩坑）

**结论：`tools/ss_level_tests.py` 不能在现场在用期间随手跑。**
L2 套件里有**会真实接触真机**的用例（`t_sssensor_real`、`t_sobs_realalign`、`t_*_real*` 这一族，会读真机 / 驱动 aligner）。实测：在现场机上跑完一次 `--level L2`，控制器随即出现**关节限位报警**（`/real_joint_states` 读得 j3 = −2.95 rad = **−169°**，已在限位），且 `/robot_status` 的 `operation_state` 落进 **`drag`**。

## 规矩
- 现场在用期间**不跑 L2/L4 全套**；要回归就到离线/无臂环境，或只挑不含 `_real` 的用例。
- 跑之前先 `pgrep -af 'ss_level_test[s].py'` 确认没有别的实例（多实例并发 = 多次真机动作）。
- 必须 xvfb（`xvfb-run -a ./gui-venv311/bin/python tools/ss_level_tests.py --level L2`），不加会有 4 条假失败（3 条 `ModuleNotFoundError: tools.gui` + 1 条无 DISPLAY）。

## 报警复位（需现场授权）
```
ros2 service call /rokae_recover_estop std_srvs/srv/Trigger '{}'
ros2 service call /state_machine/reset    std_srvs/srv/Trigger '{}'
```
实测两条都回 `success=True`（前者消息："not in emergency stop state: PowerState.on；急停恢复后 joint_and_pose 反馈已恢复"；后者："状态机已复位"）。

**复位后必须再读一次 `/robot_status`**：实测复位后 `operation_state` 变成 `drag` —— 而 **drag/柔顺模式下指令会被应答但不执行**（这是"发下去没反应"的头号根因）。

## 读真值与判“指令为何不执行”
- 关节真值：`/joint_states` 经常回空（QoS）⇒ 用 **`/real_joint_states`** 或 `/robot/joint_states`（`--qos-reliability best_effort`）。
- 姿态类指令“被接受但不执行”的三大根因（均实测确认）：
  1. `operation_state == "drag"`（切回 `idle` 后同样的指令立刻生效）；
  2. **目标方向会顶到关节限位** —— 例：j3 已在 −169°，再往同侧转必被拒 ⇒ 换**反方向**（把关节“退绕”回中间），或先手动拖离限位。
  3. **腕部/臂奇异位形**（现场定性原话：“刚才是奇异点异常”）—— 奇异点上 IK 无解，服务会返回 success 而伺服不动。表现与 1/2 一模一样（位置通道好、姿态一动不动、位置漂移 0.0mm）⇒ 判据：读 `/real_joint_states`，若 j5 ≈ 0 或某些轴组合进入腕奇异性，就是它；处置：离开奇异位形（手动拖出一点）或换 IK 另一支。
- 位置类指令（`L2.lift` / 直线位移）与姿态类指令走的是不同路径：本次现场 `lift +50mm` 正常、回位 0.0mm 残差，同时姿态一动不动 ⇒ 用这种“位置好/姿态不动”的对照快速定性。

---
name: ros2-service-contract-discovery
description: "Use when 厂家 ROS2 服务无文档: 探测字段/枚举/长度规则。"
version: 1.0.0
author: hermes-agent
license: MIT
metadata:
  hermes:
    tags: [ros2, vendor-driver, service, probing, reverse-engineering, robot]
    related_skills: [real-arm-motion-control, rokae-direct-control, orin-lan-direct-access]
---

# 无文档 ROS2 服务: 把契约"问"出来, 不靠考古

## When to Use (触发)
- 要调厂家的 ROS2 服务(驱动/产线自带), 但字段语义、枚举取值、数组长度规则没文档。
- 调用只回一句话的失败(如 `第 1 段 type 非法: move_line`), 你不知道它要什么。
- 你正准备对 `.so` 做 `strings` 或翻源码找枚举 —— 先看这里, 有更快且更安全的路。

## 核心认识: **拒绝是无副作用的 ⇒ 探测是安全的**
厂家服务的失败几乎都在"参数校验"阶段: 校验不过 = **零动作**, 且 message 里直接写明缺什么。
⇒ 每次失败都是一次**规格增量**, 不是死胡同。把 message 当文档读。

## 步骤
1. **先枚举图, 再看类型** —— 服务名与类型在**任何能看到该 domain 的机器**上都查得到:
   `ros2 service list` / `ros2 service type <name>`。
2. **拿字段布局必须在源了工作空间的那台机器上**:
   `source /opt/ros/<distro>/setup.bash && source install/setup.bash && ros2 interface show <pkg>/srv/<Name>`。
   报 `Unknown package '<pkg>'` ⇒ 这台机器没装消息包 ⇒ **也只能从装了的那台机器发**:
   在别处 `ros2 service call` 直接回 `The passed service type is invalid`(名字在图里能查到 ≠ 这能调)。
3. **构造"无副作用"的探测载荷**: 把所有目标/路点设成**当前状态本身**(从反馈话题读实时值) ——
   这样即使服务**接受**并执行, 也等于什么都没动。
4. **枚举字段靠试**: 换候选值反复发, 只回 `success=False` + 明确 message; 拿到 `success=True` 即命中。
5. **载荷被接受后**才发真目标; 完成判据一律用**带外真值**(状态话题), **不看返回码**。

## 通用坑(逐条都能咬人)
- **等长数组**: 命令类服务常要求几个数组长度一致(`move_types`/`poses`/`joint_states`/`speeds`/`zones`),
  报错会直接写 `…数组长度必须一致: move_types=3, joint_states=0`。缺的那个用**空元素消息**填即可
  (笛卡尔指令给空 `JointState()`), 不必造真实数据。
- **单元素序列会挂住**: 只有一段的"序列/轨迹"命令, 驱动的 idle 等待可能**永不返回** ——
  脚本白等几分钟而目标机器一动不动。**永远发 ≥2 段**, 只想走一步就把**当前状态当第 1 段**。
- **驱动的 `wait_until_idle` 有固定上限(常见 30s)**: 长动作会先返回
  `success=False (…IDLE_TIMEOUT)` **而动作其实继续跑完**。⇒ **绝不凭 success=False 重发**
  (重发 = 叠加第二个动作); 该标志可能顺手把 `has_error` 置 true, 下一次成功动作会自动清。
- **编译产物里捞枚举是浪费**: 处理逻辑常在 `install/<pkg>/lib/python3.10/site-packages/<pkg>/*.so`,
  而 `install/<pkg>/lib/<pkg>/<name>` 只是几十行的入口壳。`.so` 的字符串表常被压/剥, `strings` 出不来;
  即便出得来, 也不如第 4 步直接试快。
- **只看 message, 别把整段回执 dump 进上下文**: `ros2 service call … 2>&1 | grep -aE 'success|message|非法|必须|长度'`。
- **自写 rclpy 节点收不到反馈**: 反馈话题若是 **BEST_EFFORT**, 默认(RELIABLE)订阅**一条也收不到**,
  只在启动时打一行 `New publisher discovered … incompatible QoS … Last incompatible policy: RELIABILITY`。
  用 `QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST)`。
  自检: `ros2 topic echo` 能收到而自写节点收不到 ⇒ QoS 不匹配。
- **多步循环跑在"有工作空间的那台机器"上**: 不要每一步都从别的机器 ssh 过去。
  一次 ssh 起一个本地循环 + 本地自检(读反馈、算偏差、不达标就停), 否则每步往返延迟会让
  本来连续的动作看起来"走走停停"。

## 取证口径(交付时一起给)
每次探测/下发都留: ①解析到的 `message` 原文 ②下发前后的**带外真值** ③本步耗时。
"被接受"与"真做到"是两件事, 必须分开取证。

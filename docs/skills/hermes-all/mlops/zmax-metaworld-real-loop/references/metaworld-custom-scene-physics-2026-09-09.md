# metaworld 定制演示场景物理 (2026-09-09 v5.5.3: 90°外力旋转 + 光耦合压电台)

场景: L4 演示 = 来料转台把光模块桌面水平旋转 90°(干扰)→ 夹爪绕z转90° 姿态适配抓 → 回正 → 光耦合压电台 η 收敛。
产物: `tools/gen_l4_demo_scene.py`(定制 XML)+ `tools/gen_l4_demo_video.py`(全链出片 success=True 4650步)。
全部实测有效,别信注释/常量几何。

## 定制场景 XML(回归零影响)
- XML 写在 **metaworld 包内** `assets/sawyer_xyz/sawyer_peg_insertion_side_l4.xml`(同目录 include 相对路径 `../…` 全部有效)。
  生成器运行时把模板写入包路径(不入库包),原 XML 不动 → 训练/回归 env 零影响。
- env 子类覆盖 `model_name` property 返回定制 XML 路径即可加载:
  `class L4PegEnv(SawyerPegInsertionSideEnvV3): @property def model_name(self): return L4_XML`。
- 新活动 body(hinge/free)必须给 `<inertial>`(mass+diaginertia),否则 "mass and inertia of moving bodies must be larger than mjMINVAL"。

## mocap(夹爪)姿态控制
- metaworld `set_xyz_action` **每步把 mocap_quat 重置为 [1,0,1,0]** → 直接设 quat 无效。
  patch 实例方法: `_orig(action)` 后按 `env._grip_yaw` 覆盖 `mocap_quat = qz(yaw) ⊗ 默认`。
- 夹爪绕z 转角 ~300 步才收敛(weld 约束拖 sawyer 臂,振荡 78→119→92°);抓取/回正动画里可接受,给足步数。
- **夹持中旋转必须渐进 ramp**(0.005-0.012 rad/步): yaw 一步跳变 = 猛拉 peg 甩脱。
- **不能往 XML 加 actuator**(位置伺服锁台之类): metaworld `do_simulation` 校验 ctrl 长度必须 = nu,
  nu=2 假设被破坏 → env.reset `_reset_hand` 直接崩。位置锁定别用 actuator。

## 90° 旋转物理陷阱(实锤链)
1. peg 防滚 `diaginertia="100000"`(metaworld 原 XML)→ 夹持旋转需 τ=I·α 差 4 个数量级,物理不可能。
   演示场景改**真实盒惯量**: 0.24×0.03×0.03m m=0.1 → Ix=1.5e-5, Iy=Iz=4.9e-4(m/12·(L²+w²))。
2. 摩擦带不动 peg 转(即使 friction 2)→ **治具携带**: 每帧把 peg qpos 设为转台位姿 + 同步旋转角
   (真空/定位销语义,产线真实)。peg 与转台刚性随动,释放后稳定不漂。
3. 治具解除时机:**夹爪到位后、闭夹前一刻解除**。钉着闭夹 → pad 夹不住(刚性抗夹);
   提前释放自由落 → 180° 相位随机(peg 头朝向随机,插孔方向乱)。解除后立即闭夹,相位保持。
4. 夹持旋转滑脱 → peg 表面 friction 提 5(演示 XML 内 peg geom 加 friction,接触摩擦提高)。
5. **刚性夹持等效**(关键,解决全部掉件/滑移/相位): 闭夹后记录 peg 相对 hand 的 rel pos+rel quat
   (rel_q = conj(hand_q)⊗peg_q),此后每帧 env.step 后把 peg qpos 钉回 hand 位姿(pos = hand + R_hand·rel,
   quat = hand_q⊗rel_q)。等效真机刚性手爪;仿真摩擦夹持长距离转移必滑脱掉 peg(实测反复)。
6. free joint 只能 **worldbody 顶级**(嵌套报 "free joint can only be used on top level")。
7. 本机 free body qpos 布局实测 **[pos3 前 + quat4 后]**(设 qpos[adr:adr+3]=xyz, qpos[adr+3:adr+7]=quat)。

## 压电台微动(slide joint 有大坑)
- **slide joint 无外力自己匀加速滑走**(≈g,疑似 limit/solver 数值,实测设 qpos 后 20 步滑 13mm)→ 弃用 slide。
- 用 **free body 每帧强钉**: 台 x/y 每步 = 当前 + 0.5·δ(行程 ±2mm 脚本 clip),z/姿态恒钉;
  free body 无 z 支撑,不钉每帧必落下(实测台从 0.044 掉到底座上)。
- 光耦合 η 收敛 = δ(模块头 pegHead − 光纤基准 cp_ref,只算 xy)每轮 0.5 比例微动,
  η=exp(−δ²/2σ²),σ=4mm(L4-C04 性能流形标定);实测 δ0=(1.5,1.2)mm η0=0.89 → 6 轮 δ=(0.01,0.01) η=1.0000。
- 放件后 **真空治具吸附**(peg 钉台位,同治具机制)再微动,不要靠 peg 与台面摩擦跟动(软渗透不可靠)。

## 伺服/出片
- 夹持柔性系统大增益 P(err×25)振荡不收敛 → **peg 头直接闭环**: 目标 hand = 期望peg头 − (peg头−hand)
  每步重算(抗滑移)+ 步进平滑限幅 ≤2mm(act = clip(err/0.002,±1)·0.2)。
- 深插(peg-insert 孔)需要引擎级力控(六层,引擎 full 链 867 步验收),裸 P 伺服卡孔口 →
  演示链插入段降级"**对接入位**"(peg 头送达孔口中心,判据 <15mm),如实标注"深度插拔=引擎 full 链工艺";
  success 判定 = 核心段(干扰/适配抓取/回正/光耦合)。
- 出片: metaworld env.render()(rgb_array corner2)每 3 步 1 帧, cv2 写帧 + ffmpeg -framerate 25。
- **演示验收偏好**: "外力干扰动作"必须清晰渲染(转台机构可见 + 旋转后停顿展示横放 90°),
  机器人"看到"被干扰的光模块后(夹爪先绕z转90° 对正 = 识别到姿态变化的可视表达)才抓取。

## 关键命令
```
./gui-venv311/bin/python tools/gen_l4_demo_scene.py   # 写定制 XML 到 metaworld 包
MUJOCO_GL=egl ./gui-venv311/bin/python tools/gen_l4_demo_video.py   # 全链出片 (reports/l4_demo_*.mp4)
```

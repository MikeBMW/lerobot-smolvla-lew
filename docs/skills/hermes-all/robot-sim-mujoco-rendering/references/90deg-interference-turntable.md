# 90° 外力旋转干扰 + 夹爪回正抓取 — 探针实锤(2026-09-09)

场景: metaworld peg-insert-side-v3 (光模块=peg free body, 0.24×0.03×0.03m 长条盒)。
用户语义(两次强调): 演示要看到光模块**在桌面被外力水平旋转90°** 的动作过程,
不是初始就摆成 90°。视频必须演出"干扰发生 → 系统适应 → 全链成功"。

## 为什么不能直接摆 90°

- C1b 实锤: peg 绕z转90° 后长轴 ⊥ 夹爪两指开合方向(两指沿 y, peg 长轴 y→夹两端 0.24m 夹不住)。
- 真机解法 = 末端(夹爪)绕z转90° 去抓, 夹起后回正再插孔(孔轴固定 x)。

## 三处物理实锤坑

1. **peg 大惯量**: metaworld 防滚 hack diaginertia=100000 → 任何旋转 peg 的操作物理不可行
   (τ=I·α, 差 4 个数量级)。演示场景定制 XML 单独改真实盒惯量
   (m=0.1, 长轴x: Ix=1.5e-5, Iy=Iz=4.9e-4)。
2. **转 peg 的三种方式对比**:
   - qfrc_applied 扭矩(dofadr+2, 绕z): peg 转是转了但质心漂移 15.7cm → 不可控 ✗
   - 转台摩擦携带(盘 friction 2.0): 大惯量带不动, peg 转角 0.0° ✗
   - **治具转台**: 盘 hinge(qpos 手动动画)+ peg qpos 每帧同步绕z(中心钉盘心 xy、恒定托高 z)
     = 治具刚性随动(产线语义: 定位销/真空吸附) → peg 精确 90.0°, 释放后坐实稳定 ✓
3. **夹持旋转回正三要素**(缺一 peg 滑脱):
   - 抓**质心**(d.xpos[peg_id]), 不是 pegGrasp site(偏端 0.03 → 偏心甩脱)
   - peg 表面摩擦提 5.0(friction="5 0.02 0.002", 原 1.0 切向打滑)
   - yaw **渐进 ramp** 0.005 rad/步(一步跳变 = weld 猛拉 → 甩飞)
   实测: 治具转 90° → 夹爪转90° 抓 → 抬起 Δ0.136 → ramp 回正 90°→3.0°, z 保持 0.157 ✓

## env 接线与定制场景

- env.set_xyz_action **每步重置** mocap_quat=[1,0,1,0] → 直接设 quat 无效。patch 实例方法:
  ```python
  _orig = env.set_xyz_action
  def _patched(action):
      _orig(action)
      yaw = float(getattr(env, "_grip_yaw", 0.0))
      if yaw:
          qd = np.array([1,0,1,0]); qd /= np.linalg.norm(qd)
          c, s = math.cos(yaw/2), math.sin(yaw/2)
          env.data.mocap_quat[0] = qmul([c,0,0,s], qd)   # 绕世界z左乘
  env.set_xyz_action = _patched
  ```
  收敛: mocap quat 转90° 后 hand 需 ~300 env 步才到 ~90° 且有振荡(78→119→93→…)→
  先转到位再伺服位置; 夹持中回正必须 ramp。
- 定制场景 XML: 在 metaworld 包 assets/sawyer_xyz/ 下**新增**文件(如
  sawyer_peg_insertion_side_l4.xml, 由工程 tools/gen_l4_demo_scene.py 生成), include 相对路径
  全部有效(../scene/basic_scene.xml 等); 字符串 replace 注入: 新 body(转台/coupler)+ 覆盖
  peg 的 inertial/geom friction。子类 env override `model_name` property 指向它。
  **原 XML 不动 → 回归/训练 env 零影响(演示隔离红线)**。生成脚本入库, 包内文件不入 git。

## MuJoCo API 版本坑(gui-venv311)

- free joint 的 qfrc/力索引用 `m.jnt_dofadr[jnt]`, **不是** jnt_qposadr(qpos 7 维 vs qvel 6 维错位)
- mocap body 定位: `[i for i in range(m.nbody) if m.body_mocapid[i] >= 0]`(无 mocap_bodyid 属性)
- body 世界位姿: `d.xpos[body_id]` / `d.xmat[body_id]`(m.body(i).xpos 不存在)
- 移动 body(joint)必须给 `<inertial mass diaginertia>`, 否则 "mass and inertia of moving
  bodies must be larger than mjMINVAL"
- 接触 debug: 遍历 d.contact, geom 名可能为空串(依赖资产), 用 geom_bodyid 判 body

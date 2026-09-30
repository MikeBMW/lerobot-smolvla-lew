# 手眼标定 T_base_cam（2026-09-27 实测）

## 结果

| 项 | 值 |
|---|---|
| **相机→TCP 平移** | `(217.33, 5.74, -126.94) mm` · \|t\| = **251.75 mm** |
| **旋转** | 见 `handeye_result.json` 的 `T_base_cam[0:3][0:3]`（det=1.000000，正交性 2.8e-16） |
| **方法** | TSAI（PARK/HORAUD 一致，见下） |
| **有效位姿** | 8 个（he16 5 个 + he17 3 个） |
| **靶标重投影 rmse** | 中位 **0.35 px**（亚像素） |
| **闭环一致性** | 8 个位姿把靶板中心投到 base 系，**std = 1.74 mm** |
| **标定板在 base 系** | 中心 ≈ **(795, 221, 257) mm** ⇒ 在刀尖(x=534)**前方约 260 mm、上方约 30 mm** |

### 方法间一致性（判定可信度的关键）

| 方法 | t_base_cam (mm) | \|t\| |
|---|---|---|
| TSAI | (217.3, 5.7, -126.9) | 251.7 |
| PARK | (216.8, 5.8, -126.9) | 251.3 |
| HORAUD | (216.8, 5.8, -126.9) | 251.3 |
| DANIILIDIS | (221.0, 10.7, -124.5) | 253.9 |
| ANDREFF | (138.0, 3.8, -80.9) ✗ 离群 | 160.0 |

**5 位姿 vs 8 位姿结果仅差 ~1 mm ⇒ 已收敛。**

### 独立物理检验（不只看 rmse）

用**检出的 20 个圆点**做 PnP 得到板法向，经 T_base_cam 转到 base 系。
**板平放在台面 ⇒ 法向必须竖直** ⇒ 这是与 rmse 完全独立的检验：

| 位姿 | 偏竖直 |
|---|---|
| yp00_tp00 | 11.3° |
| yp00_tm14 | **9.1°** |
| yp00_tp14 | 15.3° |
| ym35_tp00 | 29.3°（斜视角，PnP 法向本身不可靠） |
| yp35_tp00 | 38.8°（同上） |

⇒ **旋转方向正确（非 90° 级错误），但仍有 9~15° 残差** ⇒ 精细抓取(需 1~2°)前须补采集。

## 采集为什么必须"双轴"

单绕世界 Z 轴偏航 ⇒ `R_i = Rz(ψ_i)·R_ref` ⇒ 相对旋转 `R_iᵀR_j` 的转轴**恒为 `R_refᵀ·(0,0,1)`**
⇒ **31 对相对旋转的转轴夹角实测中位 0.0°、max 0.0°** ⇒ OpenCV 5 种方法全给 NaN 或 10⁷ mm。

**判据（两条都看）**：
1. 位姿间旋转角 >10° 的对数 ≥3（本次 25/28 ✅）
2. **相对转轴之间夹角中位 >8°**（本次 22.2° ✅）

⇒ 采集方案必须 **世界Z偏航 × 世界X倾斜** 组合。

## 复现步骤

```bash
# 1) 采集（Orin 上跑，/move_pose 必须在 Orin 调用）
python handeye_collect17.py         # 输出 /tmp/scene/he17/

# 2) 解算（必须用 lerobot-venv：它有完整 OpenCV 的 calibrateHandEye）
/home/ubuntu/lerobot-venv/bin/python handeye_solve3.py /tmp/scene/he_all 20.0

# 3) 独立物理检验
/home/ubuntu/lerobot-venv/bin/python verify_board_normal.py
```

## 标定板档案

**CGB-020** · 5×4=20 白点圆阵列 · **20 mm 间距** · 白点黑底
检测链（缺一不可）：**1280×720** + **反相** + `findCirclesGrid((4,5), ASYMMETRIC)` + 回全图坐标做 PnP。

## 已知坑（详见技能 real-arm-handeye-calibration）

- `error_code=-50021`「指定conf参数下目标点无解」= **运动学不可达**（关节限位/奇异），与 `ROBOT_IDLE_TIMEOUT` 是**两回事**；控制器建议"不设置 confData"。
- `/move_pose` 的 `success=False` **不代表动作没执行**（实测 TCP 已到位）⇒ 一律轮询 `/robot/tcp_pose` 核对。
- speed=15 时 20° 偏转需 >30 s，顶满服务端 30 s idle 窗口 ⇒ 报 ROBOT_IDLE_TIMEOUT；**speed=50 后仅 3 s**。
- **运动中绝不重发**（重发会造成真实风险）。

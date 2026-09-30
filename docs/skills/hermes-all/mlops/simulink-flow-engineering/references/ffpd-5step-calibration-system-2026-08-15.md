# 5步新场景标定系统 (2026-08-15 老倪贴"LeftRight混合控制系统·新场景快速标定系统"要求落地到右侧标定面板)

承接 refs/ffpd-field-calibration-and-run-refresh-2026-08-15.md 的 3 步现象版,
本文件是**升级版**: StageCalibrationWidget 从"3步现象法"重写为 **QTabWidget 5 Tab 流程版**。

## 结构 (model_tree.py StageCalibrationWidget 重写)

```
🎛 总览条 (5步法: ①感知(眼睛)→②几何(尺子)→③辨识(肌肉)→④整定(节奏)→⑤验证(考官))
QTabWidget 5 Tab (每个 tab 内容包 QScrollArea 防超高):
  ① 感知: 手眼标定按钮(模拟 AX=XB 生成 camera_to_robot 4×4) + peg_xyz/hole_xyz 6 个 spinbox
  ② 几何: grasp_d_hp(实测×1.1) / transfer_tolerance(实测×0.8) / insert_tolerance(硬限位×0.5)
          三个"计算"按钮 → 结果 QLabel → 💾 写入状态机节点 (grasp_d_hp/transfer_tolerance/insert_tolerance)
  ③ 辨识: m/b/k 三 spinbox + 震荡衰减计算器(峰1/峰2 幅值 → δ=ln(a1/a2) → ζ=δ/√(4π²+δ²)
          → b=2ζ√(mk) 自动填 b 框) → 💾 写入动作节点 (m/b/k)
  ④ 整定: ωₙ spinbox + 4 阶段 ζ spinbox (接近0.7/转移1.0/插入1.5/抬起0.8)
          → Kp=m·ωₙ²−k, Kd=2m·ζ·ωₙ−b 实时刷新 (每阶段行显示 Kp/Kd/Mp%/Ts)
          → 💾 写回状态机.Kp + 动作.Kd + 动作.m/b/k
  ⑤ 验证: 原 3 步现象法 (推拉/力尖峰/切换瞬间) 原样移入
底部: 📄 导出 scene_config.yaml 按钮 + 快检表 QLabel
```

## scene_config.yaml 导出 (_export_yaml)

交付物 = `~/lerobot-smolvla-lew/configs/scenes/scene_config.yaml`:
```
scene_name / calibration_date
perception: hand_eye_matrix(4×4) + peg_ref_xyz + hole_ref_xyz
state_machine: grasp_d_hp / transfer_tolerance / insert_tolerance / lift_height
dynamics: m/b/k
gain_schedule: approach/transfer/insert/lift 各 {Kp, Kd}
```
- GUI venv 可能无 pyyaml → `try: import yaml` 失败走手写 yaml 文本分支
  (行拼接, gain_schedule 用 `{Kp: x, Kd: y}` 内联 dict)
- 手眼矩阵默认 np.eye(4), 用户点过①生成才用真实矩阵

## 🐛 QDoubleSpinBox 精度坑 (本会话验证脚本卡住的根因)

**QDoubleSpinBox 默认 2 位小数 → setValue(0.055) 被四舍五入成 0.06** (银行家舍入),
标定阈值类输入 (0.055/0.05/0.06) 全错。**任何标定/参数 spinbox 必须 `setDecimals(4)`**:
```python
def _sp(self, lo, hi, val, step=0.1, suffix=""):
    sp = QDoubleSpinBox(); sp.setRange(lo, hi); sp.setValue(val)
    sp.setSingleStep(step); sp.setDecimals(4)   # ← 必须, 否则 0.055→0.06
```
诊断信号: 断言 `round(0.055*1.1,4)` 失败 → 先打印 `repr(spinbox.value())` 看是否被
spinbox 吞精度, 别怀疑计算逻辑。

## 其他坑

- `_btn()` stylesheet 用 f-string + `{{` 转义混 `{color}` 变量会解析错乱 → 用字符串拼接
  `"QPushButton { background:" + color + "; ..."` (f-string 里 `{{` 和 `{var}` 混用不可靠)
- QTabWidget 样式: `QTabBar::tab:selected { background:#1f6feb; color:#fff; }` 选中高亮,
  未选中 #161b22/#9aa4b2 — 深色面板统一
- 写回逻辑复用: `_apply_geo/_apply_dyn/_apply_gains` 都按节点名找 z700_internal 状态机/动作,
  改 params → 遍历 nodes 的 `_items.get(n["id"]).update()` + canvas._scene.update() + _log
- 树刷新: `self._refresh_tree()` 委托 `self._pp_ref.refresh_tree_only()` (pole_place 的)
- 验证: offscreen 必须打桩 QMessageBox (模态挂死); 断言 5 tab 数/手眼矩阵 shape(4,4)/
  几何值=round(实测×系数,4)/δ→ζ→b 公式/整定 Kp=m·ωₙ²−k/导出 yaml 文件存在含关键键

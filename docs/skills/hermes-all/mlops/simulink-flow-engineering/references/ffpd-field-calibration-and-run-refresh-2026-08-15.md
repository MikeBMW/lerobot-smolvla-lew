# 前馈PD 现场标定向导 + 运行后自动刷新 + 工程师验证指标 (2026-08-15)

承接 refs/ffpd-internal-paint-and-eigen-2026-08-15.md, 本文件补老倪贴的
"3步现场标定法"(不解复数只看物理现象)落地 + "运行后如何看数学分析"联动 +
增益调度表加工程师指标(Mp/Ts/Tp/手感)。

## 📐 现场标定向导 StageCalibrationWidget (右侧下拉第 5 项)

老倪贴"3步现场标定法"要求"按照这个做标定系统" — model_tree.py 新增
`StageCalibrationWidget(QWidget)`, ModelTreeDock 下拉加 "📐 现场标定" (idx=4):

```
① 推拉测试 → Kp/Kd 比例 (ζ 手感)
   回弹超过2次   → 诊断 ζ<0.6 欠阻尼 → 应用: 动作.Kd ×1.5
   软绵绵爬回去  → 诊断 刚度不足     → 应用: 状态机.Kp ×1.3
   迅速归位      → ✅ 合格
② 接触力尖峰 → 插入极限增益 (Fz 曲线)
   尖刺台阶 15N → 诊断 速度过快/Kd过激 → 应用: 动作.Kd ×0.7 + limit 收紧×0.8
   无力反馈    → 诊断 位置环太软       → 应用: 状态机.Kp ×1.3
   平滑 S 型   → ✅ 合格
③ 切换瞬间 → 前馈/反馈衔接 (转移→插入)
   「咯噔」异响     → 诊断 速度指令断层 → 应用: 状态机.ramp_ms=50 (斜坡平滑)
   切换后静止不动  → 诊断 tolerance 松  → 应用: 状态机.transfer_tol=0.03
   顺滑无闯动       → ✅ 合格
+ 底部速查卡 QLabel (机柜贴纸文案: 速度慢→增Kp / 抖动→增Kd / 力尖峰→降限幅 / 咯噔→斜坡)
```

- **交互模式 = 选现象(QComboBox) → 诊断文本(QLabel, 含代数根因) → 💾应用按钮写回画布**
  (`_apply(step)` 遍历 z700_internal 按节点名找状态机/动作, 改 params → it.update()
  + canvas._scene.update() + _log + 刷新树)
- **新参数写回不存在的键**: ramp_ms/transfer_tol 是状态机节点新参数 — 直接 `p_sm["ramp_ms"]=50`
  即可, 画布 load 时 params 自动带上; 独立绘制 _paint_internal 的 _pkeys 白名单
  ("Kp","K_obs","K_ff","Kd","thresh") 不显示它们也 OK (默认不展示, 数据字典树可见)
- 树刷新复用: `self._pp_ref = self.pole_place`, `refresh_tree_only()` 委托 pole_place 的
  同名方法 (PolePlacementWidget 已有 refresh_tree_only, 别重复实现)
- 视图切换: `_switch_view` 里 `field = idx == 4; self.tree.setVisible(not show and not field);
  self.stage_calib.setVisible(field)`
- 验证: offscreen 下 **QMessageBox.information 模态会永久挂死验证脚本** (无人点确定) →
  **必须先打桩** `QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)`
  (同样适用于任何 _apply/_write_back 里有 QMessageBox 的验证); 另外 offscreen 下
  `widget.isVisible()` 依赖顶层窗口显示 → 用 `isVisibleTo(mt)` 断言可见性标志

## ▶ 运行后自动刷新数学分析 ("运行后,如何看你的数学分析")

老倪问"运行后如何看数学分析" → start_sim 顶层仿真完成分支加自动刷新联动:

```python
# _exec_topological() 之后, btn_run 复位之前
mt = getattr(self, "model_tree", None)
if mt is not None and mt.cmb_view.currentIndex() >= 2:
    mt._show_math() if mt.cmb_view.currentIndex() == 2 else mt._show_state_space()
```

- 语义: **用户正停在 🧮/🎛 视图 → 运行完成数据即时刷新, 不弹窗不切页** (弹窗零容忍,
  用户没在看该视图就不打扰)
- 验证: offscreen 手动挂 ModelTreeDock, cmb_view.setCurrentIndex(2), lbl_math 置旧文本,
  调 start_sim() → 断言文本含 "纯规则前馈PD" 且 btn_run 复位 "▶ 运行"

## 增益调度表加工程师验证指标 (Mp/Ts/Tp/手感)

老倪贴"各阶段工程师如何快速验证"→ root_locus 每阶段加:

```python
if zeta < 1.0:
    Mp = exp(-π·ζ/√(1−ζ²));  Tp = π/(ωₙ·√(1−ζ²))
Ts = 4/(ζ·ωₙ)   # ±2% 稳定时间
feel = {"接近":"拉紧的橡皮筋·弹射快终点轻颤", "抓取":"轻触·位置锁定",
        "抬起":"匀速上升·稳重", "转移":"粘稠糖浆·平稳不冲",
        "插入":"液压缓冲器·顺从吸入无反弹"}.get(stage, "")
```

- _show_math 增益调度段每阶段两行: 第1行极点, 第2行 `Mp=X% Ts=Xs Tp=Xs 类型` + 🖐手感
- 验收行: "阶跃超调<5% · 猛推回正≤2次震荡 · 插入力曲线平滑S型"
- ⚠️ 默认 m=1/b=2/k=5 下接近阶段 ζ=0.43 → Mp=22% (欠阻尼明显), 用户示例表的 8.2% 是
  示意值 — **显示算出来的真实值, 别凑用户表**

## 本会话 UI 修复铁律汇总 (老倪连报 5 轮后的最终认知)

1. 特殊节点类型(z700_internal)专用布局 → **paint 开头完全独立分支 + return**,
   不碰通用路径 (通用路径的残留绘制源数不清: 类型标签/参数摘要/端口/徽章)
2. 改 analyze_system 返回结构 → 同步 grep _show_math 引用 (Kd_eff/T 删除后 KeyError 崩)
3. 感知链 Kp→K_obs 改名全链路 4 处: JSON / _paint_internal _pkeys / analyze_system _p /
   on_ff_pd_config keys 列表
4. 验证脚本有模态框必打桩; isVisible 用 isVisibleTo; 像素级文本带检测判 UI 重叠

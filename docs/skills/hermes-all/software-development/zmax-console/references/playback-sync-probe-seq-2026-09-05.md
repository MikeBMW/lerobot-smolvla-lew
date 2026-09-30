# 播放同步 = probe_seq 帧流 (2026-09-05 晚, 老倪严查信号真实性)

承接 viz-layer-nodes-gui-autotest-2026-09-05 (可视化层/双击/取证/插入验收)。
本文件 = 显示层同步升级: 直方图/归因/Scope 播放逐帧推送, 3D 数据源标注。

## 症状与诚实口径
老倪 (2026-09-05): "直方图没输出; 归因一直输出 4 个格子的帧; 仿真波形不动;
3D 一直自己播放没同步; 这些信号到底是不是运行时的输出, 严查"
- 诚实结论: 数值 100% 引擎真实算 (六层源码每步真执行, 无编造), 但显示层有真缺陷:
  ① 播放 = "引擎 run() 一次全跑完 → 动画回放" 模型; 旧实现 hist/attr 只拿末帧探针 → 静止;
  ② ▶运行默认 = 真实化 (RealStateSpaceSim) 的 run() 当时不收集逐帧探针 → 帧流缺失;
  ③ 3D 没先 ▶运行 就打开 → 退回预录 episode 自播放 (与画布无关, 看起来"不同步")。
- 老倪"4 个格子的帧" = 归因堆叠窗口单帧柱的 4 色段 (dx/dy/dz/gripper 四输出维) +
  顶部 4 色图例; 数据不动时画面静止。窗口必须能自解释: 状态行带帧数/当前主导维。

## 修法 = 每步探针快照 + 播放同游标逐帧推送
1. **引擎 run 每步存 probe 全序列** (两处都要!):
   `state_space_sim.py` (StateSpaceSim) 与 `state_space_sim_real.py` (RealStateSpaceSim)
   run() 内 accel.forward 之后:
   ```python
   tr["probe_seq"].append(dict(accel.probe))   # dict 浅拷贝; act_raw 是数组引用
   ```
   tr init dict 同步加 `"probe_seq": []`。真实化遗漏 = "默认 ▶运行 直方图没输出"根因
   (简化引擎先加了, 真实化没加 — 用户默认路径反而没数据)。
2. **_ss_tick 播放 tick 逐帧推窗口** (与 3D/画布/DataWorld 同一游标 idx):
   ```python
   ps = tr.get("probe_seq") or []
   if ps and idx < len(ps) and self._ss_round % 2 == 0:
       _p = ps[idx]
       if self._ff_hist_win:  self._ff_hist_win.push(_p)
       if self._ff_attr_win:  self._ff_attr_win.push(_p)
   ```
3. **Scope 播放增量**: `StateSpaceScopeDialog.set_cursor(idx)` → self._cursor + update();
   _paint 开头按 cursor 算 `_k` (前缀长度), 所有曲线/mani_rem/mani_dperp/_stages 切片
   [:_k]; `_playing = cursor is not None and _k < len(t)` → 底部摘要显示
   "▶ 运行播放中 t=…" (播完才显示 ✅验收 verdict)。建窗处登记窗口列表
   (`self._ss_scope_wins.append(dlg)`) 供 _ss_tick 推光标。
4. **归因窗口自动投影 + 状态行**: push 内满 10 帧自动 `_project("pca")` (散点不等手动
   按钮); hist/attrib 的 push 都更新顶部 QLabel 状态行 (累积帧数/当前 u_ff/主导输出维/
   读图解释) — 窗口"活着"可感知, 且回答"这是啥"。

## Scope set_cursor 实现坑 (实测崩)
- 阈值线代码的局部变量**别叫 `_tv`**: _paint 外层 `_tv` 是时间数组; 第 7 格阈值线
  `_tv = float(opt["thr"])*1000` 覆盖成 float → 第 8 格 (ins 格) `_t = _tv; len(_t)` 崩
  "TypeError: object of type 'float' has no len()" (paintEvent try 吞掉 → 窗口全空,
  内容比 0.001)。改名 `_thr_v`。
- 自绘 paint 全部 drawText/fillRect 坐标 int() (老坑重提)。

## 3D 数据源标注 (一眼可辨, 不混淆)
- open_ss_3d 数据源确定后给 tr **副本**打标 (别污染引擎轨迹):
  ```python
  tr = dict(tr); tr["_viz_src"] = "run"        # 程序执行轨迹
  tr = dict(ep); tr["_viz_src"] = "episode"    # 预录 episode 回放
  ```
- DreamView3D.set_trajectory 读 _viz_src 设窗口标题:
  "🧭 3D 视图 · 程序执行同步 (▶运行/⏭到哪步, 3D 到哪步)" vs
  "🧭 3D 视图 · EPISODE 回放 (预录, 非本次运行 — 先 ▶运行 转同步)"。
- 播放 tick 直接喂引擎 tr (无 _viz_src) 时: `module._ss_tr is tr` → 判为 run。

## 一键自动测试 = GUI 可视化演示 (Test 节点右键 ⚡)
- `_run_auto_test` 先跑 `_auto_test_demo(on_done=…)`: 主线程 `_oneshot` 链
  (60/90/120/150/180/220ms): 引擎 `_ss_ensure_trace(force=True)` → 依次
  show_state_space_scope / _open_viz_node(hist, 喂 parquet 150 帧真实 obs 回放) /
  attrib (自动 PCA) / open_ss_3d / play_mlp_rollout — 每窗停留 1.2s 用户可见,
  grab() 存 reports/viz_evidence/viz_*.png → on_done 才启动后台子进程跑全量用例+报告。
  演示段窗口查找: scope = self.findChildren(StateSpaceScopeDialog); 3D/视频 =
  QApplication.topLevelWidgets() 按类名 (DreamView3D/MLPRolloutDialog)。
- 依赖: 直方图/归因窗口单例挂 module (`_ff_hist_win`/`_ff_attr_win`), 构造带
  parent=self + 显式 Qt.Window flags (min/max 可用, 见 qdialog-maximize 类坑) +
  `_show_nonmodal` + `_popup_on_main_screen` (直接 show 在 WSLg/多屏会弹屏外=看似没反应)。

## 真实双击链路验证 (三层, 别只调函数)
- 真实 GUI 双击 ≠ 直接调 on_node_activated: SimCanvas.mousePressEvent 手动双击检测
  (0.4s 内同 item 两次左键按节点主体) → module.on_node_activated; 点输出端口 =
  连线模式 (不触发双击); 慢双击/点空白 = 无反应。
- 验证三档: ① 函数直调 module._open_viz_node(kind); ② item.scene_ref.on_node_activated;
  ③ **真实鼠标事件**: QMouseEvent(MouseButtonPress, viewport pos=节点中心) 发两次
  (QApplication.sendEvent(view.viewport(), ev), 间隔 0.15s) — 第三档才等于用户双击。
- 用户双击"还是没反应"排查顺序: 重启 studio (代码改了必须重启, 给 pid+版本证据) →
  双击留痕日志 (viz_kind 分派前 self._log "🔭 双击可视化节点 X → 打开 Y") →
  右键菜单加「🔭 打开显示窗口」可靠入口 (不依赖双击时序/位置) → 屏外弹窗排查。

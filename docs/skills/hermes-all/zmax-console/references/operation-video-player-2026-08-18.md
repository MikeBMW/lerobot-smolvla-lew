# 操作视频节点 — 语义与播放器实现 (2026-08-18 老倪纠正后)

## 语义 (用户明确纠正)
- **「🎥 操作视频」= 机械臂操作动作视频** (MLP rollout: reports/*MLP*.mp4 /
  *mlp*.mp4 — metaworld 里机械臂插拔动作)
- **不是仿真波形动画** state_space_sim.mp4 (Pillow 渲染的轨迹/波形动画) —
  那个属于「📊 仿真波形」节点 (StateSpaceScopeDialog)。仿真完成自动生成的
  state_space_sim.mp4 只发链接 (datadrive.world), **不进操作视频播放列表**
- 操作视频双击 → 独立大窗口播放 (MLPRolloutDialog), 画布内嵌播放已废弃

## MLPRolloutDialog 实现要点 (simulink_module.py)
- QDialog: 初始 1280x820, min 1024x700, sizeGrip + maximize; 深色底
- QLabel 显示帧 (KeepAspectRatio 缩放), 底部按钮: 上一个/暂停/下一个/转正 180°/左右翻转
- **180° 旋转 = `pm.mirrored(True, True)` (位图快速操作)** — QTransform().rotate
  SmoothTransformation 每帧全像素变换是卡顿根因 (VcXsrv 软渲染)
- 播放中缩放 FastTransformation, 暂停/翻转 Smooth; **循环播放** (勿自动暂停=误判卡住)
- 抽帧: 后台线程 ffmpeg → PNG 缓存 (reports/_mlp_cache_<名>/), 缓存命中秒开;
  完成信号回主线程 (pyqtSignal)
- 事件虚函数 (resizeEvent/paintEvent/closeEvent) 全部 try 包裹 (qFatal 铁律)
- **关闭后引用悬垂**: 主窗口 self._mlp_dlg 用 sip.isdeleted 检查, 悬垂置 None
- timer 用 _tq(parent) PreciseTimer 挂 parent

## 视频选片 (play_mlp_rollout)
- 优先级: mlp_insert_success_final > mlp_insert_success > mlp_best_final > mlp_best
- **排除 rot180/rot 变体** + **伪装副本「发送_MLP插拔成功.mp4」** (字节数与
  mlp_insert_success_rot180.mp4 完全相同 = rot180 副本, HUD 文字倒)
- 排序: sorted(key=_PRIORITY.index or 99, -mtime) — **新视频必须进 _PRIORITY 否则排最后**
- **MLP 视频默认 rot=180 画面正** (✅ 2026-08-19 老倪确认: 生成端画面本身反需180°转正;
  HUD 文字原方向正 — OCR 实锤 rot0 下 "TREND peg->hole inserted / hand->peg" 可读。
  **画面与文字方向矛盾, 播放端以画面为准; 文字也要正 → 生成端重生成视频**)
- 🐛 播放中 90/270° 旋转必须 FastTransformation — Smooth 每帧全像素插值
  (100ms tick × 780x480) = "很卡"根因; 暂停时才 Smooth (2026-08-19)
- 窗口标题/按钮禁 emoji (VcXsrv wqy 无 emoji 字形 → 显示 ?? / □)

## 诊断小技巧
- **判定视频文字方向 (最可靠): tesseract OCR 8 方向测试** — 对一帧做 4 旋转 × 2 镜像,
  OCR (chi_sim+eng, psm 11) 识别出真实词组 (TREND peg->hole 等) 的方向 = 字正方向。
  判定脚本: 本技能 scripts/ocr_dir_check.py (2026-08-19 沉淀; 用法见文件头)
- 判断视频是否旋转变体: 抽帧 ASCII 粗看主体在左/右 (rot180 版主体左右互换);
  或对比字节数 (伪装副本 = 同字节)
- 仿真动画与 rollout 视频别混: 用户说"操作视频"默认指机械臂动作视频

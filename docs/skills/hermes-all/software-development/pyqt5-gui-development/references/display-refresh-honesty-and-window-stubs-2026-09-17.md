# 显示类窗口的"诚实性" + offscreen 验证真窗口的桩写法 (2026-09-17 实测)

> 背景: Z-MAX「输入图像」窗口连吃两问 —— 「点了运行仿真图像不动」+「没连真机选真机还在放 metaworld 视频」。
> 两条根因不同, 但**都是同一族**: 画面在骗人。PyQt5 里凡是标着"实时/实况"的窗口, 都要有硬判据。
> 完整项目案例 (含脚本) 见 zmax-console `references/sim-live-frame-and-no-frame-honesty-2026-09-17.md`。

## 一、「显示类」刷新条件不能只有"数据变了"

**症状族**
1. 切换输入源后屏上还是上一路画面 (真机/仿真/回放互相残留);
2. 数据断了画面纹丝不动, 用户以为"还在放实时视频";
3. 无人操作时一直显示几小时前的旧帧, 状态栏却写着"无新帧"—— 文字与画面打架。

**两条根因 (同族)**
- 重画条件写成"**文件签名变了才重画**": `sig = (mtime_ns, size); if sig != self._last_sig: 重画()` —
  没有新数据 ⇒ 签名不变 ⇒ 永不重画 ⇒ 上一路的 pixmap 就留在控件里。
- 切源代码只切了**链路/定时器**, 没清**画面 / 框 / 签名缓存**。

**修法三件套**
1. **切源即清屏**: 清 `_last_sig` `_pending_sig` `_fresh_since` + `set_boxes([])` (上一路的框属于上一路帧坐标系)
   + 立刻给占位画面;
2. **占位画面自己合成** (别指望 `set_frame_rgb(None)` 会清屏 —— 常规实现是 `if rgb is None: return` 保留旧图):
   ```python
   img = QtGui.QImage(w, h, QtGui.QImage.Format_RGB888); img.fill(QtGui.QColor("#0d1117"))
   p = QtGui.QPainter(img)
   p.drawText(QtCore.QRect(24, y, w - 48, 320), QtCore.Qt.TextWordWrap | QtCore.Qt.AlignTop, "⚠️ 无数据: 原因…")
   p.end()
   stride = img.bytesPerLine(); buf = img.constBits(); buf.setsize(stride * h)
   arr = np.frombuffer(bytes(buf), np.uint8).reshape(h, stride)[:, : w * 3].reshape(h, w, 3)  # QImage 有行填充, 必须切
   ```
3. **只有"新鲜帧"才允许上屏**: 新鲜度判据 (`ok ∧ age ≤ 阈值`) 写在重画**之前**; 超时 N 秒 → 换占位画面并写明
   **原因 + 最后帧时间**; **冻结/标定态不顶掉画面** (用户正在标的帧不许被冲掉)。

**给画面打来源标记**: `self._view_tag = "real" / "sim-engine" / "sim-idle" / "waiting-real" / "stale-real" /
"no-frame-real"` —— 显示语义可被程序断言, 也让"现在到底在放什么"一句话说得清。

**原则**: 无数据时**画面本身要给结论**; 不许拿旧图、更不许拿另一路的图冒充实时。
"实时"类窗口必须存在「新鲜度 → 上屏 / 占位」这条硬判据, 否则迟早被用户抓获。

## 二、同进程"实况帧"同步 (生产者/消费者都在 GUI 进程内时)

窗口要跟另一个模块的运行状态同步时, **别自己另开一个渲染器/数据源** (重复渲染 = 两份真相, 且 mujoco/GL
这类后端非线程安全)。正解 = 进程内共享槽 + 节流状态文件:
- 生产者每步把**它真正用到的那一帧** (例如 detect_3d 的输入帧) 挂到模块级 dict `{"t","step","rgb","consumed"}`;
- 消费者读取时判新鲜度 `max_age`, 过期返回 None (退回诚实占位, 不许假动);
- 消费端声明 `want` 标志, 生产者据此决定"没人看就不干活" (零开销);
- 1Hz 节流写一个状态文件 (步号 + 消费计数) ⇒ **外部可核对**, 比截图/OCR 可靠 (GUI 进程内外都能验)。

## 三、offscreen 验证真窗口的桩写法 (三个必踩坑)

1. **数据目录用环境变量重定向**: 模块级常量 (`LIVE_JPG`/`LIVE_META`/`ANNOT_ROOT`) 在 import 时读 env →
   测试里先 `os.environ[...] = tempfile.mkdtemp()` **再 import**, 造帧/写 meta 全在临时目录。
2. **外部副作用 (ssh/docker/子进程) 用 classmethod 打桩**:
   `mod._RemoteChain.ensure = classmethod(lambda cls: "测试桩")` —— 类实例方法直接赋 lambda 会缺 self 绑定报错;
   不打桩真会去起真实链路 (测个画面颜色却 ssh 了生产设备)。
3. **⚠️ 别用"换实例属性"拦代码路径**: `win._start_source = lambda: None` **拦不住**
   `QTimer.singleShot(200, self._start_source)` —— 那是 `__init__` 里**已捕获的 bound method**, 定时器到点仍调原函数;
   而且后续真正要测的 `_start_source` 内部逻辑 (清屏/占位) 根本不执行 ⇒ 断言**假 PASS**。
   要拦就拦**更下层的副作用函数** (见第 2 条), 让被测函数照常执行。
   判定信号: 断言通过但看不出预期行为痕迹; 换个字段 (如 `_view_tag`) 或加 `print` 才发现根本没动。

**断言"画面真的换了"用像素字节比对**: `pixmap().toImage()` → `constBits()` → `bytes(...)`, 前后不同才算换过;
别用 `isVisible()` / 对象存在性代替 (同族教训: "入口控件 exists() 证明不了人点得到")。

## 四、测试脚本自身也会误报 (本次两例, 都已修正)
- 断言"落盘内容 = 最新 step"时忘了**节流窗口**: 1Hz 节流下首帧写的就是当时那一步 → 正确断言 = 睡过节流窗口后再发一帧,
  文件必须刷新 (否则拿正常行为当 bug)。
- 断言"切源会清屏"时把**入口方法换成了桩** → 清屏代码没跑却通过 (见第 3 条坑)。
  **每写一条断言都问一句: "这条路径在我的桩下真的执行了吗?"**

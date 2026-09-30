# GUI 改码安全 + 无副作用冒烟 (2026-09-19 实测: 一晚连崩控制台两次 + 一次误动机器人)

## 一、铁律: 改完必须"真构造 + 真跑改过的 handler", 语法 OK 完全不算数

三个真实崩法(全部发生在同一次 UI 改造里):

1. **半截补丁 = 启动即崩**
   - `self.btn_l2_muscle.clicked.connect(self._run_l2_muscle)` 写了, 但 `_run_l2_muscle` 方法没写进去
   - 构造时 AttributeError → 异常抛在 Qt 槽/构造链里 → **进程 SIGABRT(134) 整体退出**
   - 日志尾只有 `Fatal Python error: Aborted` + 线程栈(栈顶端就是崩溃点) → 用户现象: "控制台没了"

2. **分支插在函数开头 = UnboundLocalError → 同样 Fatal**
   - 在 `_go()`(点击"开始")顶部插:
     `if isinstance(s, dict) and s.get("id") == "L2.aoi_picture": ...`
   - 而 `s = it.data(32) or {}` 在函数**后面**才赋值 → `UnboundLocalError: local variable 's'` → Fatal
   - 修法: 分支一律插在它依赖的变量**赋值之后**; 插完把该 handler 真调一遍

3. **按 `def` 边界切片换方法会连带删掉中间的东西**
   - 用 `s[:i] + NEW_SEL + s[j:]` 换 `_sel`(i=`    def _sel(`, j=下一个 `    def `)
   - 结果把两方法**之间**的类属性 `IMG_URL = "http://..."` 一起删了 → 后续 `AttributeError: 'L2SkillDialog' object has no attribute 'IMG_URL'`
   - 修法: 换方法前先打印这段区间原文, 看清里面除了该方法还有什么

**验证顺序(缺一不可)**
1. `ast.parse` (只挡语法, 挡不住上面三种)
2. `python -c "import <模块>"`
3. 真构造窗口/对话框实例
4. **对每个改过的 handler 真调一次**(这次就是靠它才发现 `_sel` 里 `float("home")` 崩)
5. 控件属性名先查(`dlg.lst` 而不是 `dlg.list` —— 猜属性名会让测试白跑一轮)

**改文件的方式**
- 优先 execute_code 读-改-写: 读全文 → `assert s.count(ANCHOR) == 1` → 改 → `ast.parse` → 写回
- 锚点先 `grep -n` 看原文再写(猜锚点会静默 no-op, 或 indentation 对不上写坏文件; 这次赔了两轮)
- 终端 heredoc / write_file 在超长会话里会被截断(单次只剩几百字节) → 大段改动走 execute_code

## 二、冒烟测试绝不允许有副作用 (老倪逐字: 「不用把所有技能都跑，别动机器人」)

- 我写的对话框冒烟脚本对**全部 10 个技能**依次调了 `_go()` → `_go()` 写 FIFO → 常驻执行器 → **机械臂真收到 6 条运动指令**(抬升/下降/平移/合爪/到点)
- 用户当场制止; 事后核对执行器日志才知道发了什么
- **规则**:
  - UI 测试只覆盖"选择/渲染/布局/构造"
  - **任何会下发命令的 handler 一律 dry-run, 或把下发层打桩**(stub `send()` / publish / HTTP client), 并在输出里显式打印 "未下发"
  - 测完立刻读后端/执行器日志确认没有真请求, 再对外说"通过"
- 反面: 用户明确授权的**只读类**技能(AOI 拍照检测, 不动机械臂)可以直接实测 ✓

## 三、暗色对话框可读性 (老倪: 「字体是黑色背景也是黑色，看不清 → 改亮色」「字体也太小了，增大一些」)

- 症状: 自建 QDialog 跟随主程序深色主题时, **默认 palette 仍是深色前景** → 黑字黑底
- 修复: 对话框 `self.setStyleSheet(DARK_QSS)` 显式给全:
  ```python
  DARK_QSS = """
  QDialog, QWidget { background: #1b1e24; color: #e8e8e8; }
  QLabel { color: #e8e8e8; font-size: 16px; font-weight: bold; }
  QListWidget { background: #12141a; color: #eaeaea; border: 1px solid #333; font-size: 17px; }
  QListWidget::item { padding: 10px 8px; color: #eaeaea; }
  QListWidget::item:selected { background: #2d4f6b; color: #ffffff; }
  QDoubleSpinBox, QSpinBox, QComboBox, QLineEdit { background: #12141a; color: #ffffff; border: 1px solid #3a3f4b; padding: 6px; font-size: 17px; }
  QPushButton { background: #2a2f3a; color: #f0f0f0; border: 1px solid #46506a; padding: 8px 16px; border-radius: 4px; font-size: 16px; }
  QPlainTextEdit, QTextEdit { background: #0f1115; color: #d8e0d8; border: 1px solid #333; font-size: 14px; }
  """
  ```
- **字号要大**(老倪偏好, 单色勿彩高亮): 列表 17px/行距 10px · 标签 16px 粗体 · 输入 17px · 按钮 16px · 日志 14px · 窗口 820x620(原 640x470)
- 可量化验证: offscreen `dlg.show(); dlg.grab()` → 存图并数像素: **亮像素(lum>170) 与 深像素(lum<60) 都必须 >0** (全深 = 字没渲染或黑字黑底)

## 四、参数控件: 数字用 SpinBox, 枚举/字符串用 ComboBox

- 崩因: `self.spin.setValue(float(meta.get("default", 50)))` 遇到 `{"default": "home"}` → `ValueError: could not convert string to float: 'home'`
- 正解:
  ```python
  try:
      num = float(meta.get("default")); is_num = True
  except (TypeError, ValueError):
      num, is_num = 0.0, False
  self.spin.setVisible(is_num); self.spin.setEnabled(is_num)
  self.combo.setVisible(not is_num)
  if is_num:
      self.spin.setValue(num); self.spin.setSuffix(" " + str(meta.get("unit", "")))
  else:
      if self.combo.count() == 0:
          for v in (meta.get("values") or [候选表]): self.combo.addItem(str(v))
      i = self.combo.findText(str(meta.get("default")))
      if i >= 0: self.combo.setCurrentIndex(i)
  ```
 取值: `k0 = list(p.keys())[0]; spec[k0] = self.combo.currentText() if (self.combo.isVisible() and self.combo.count()) else float(self.spin.value())`
- 下发字段按技能类型裁剪: 运动类才带速度 `if s.get("ros") != "http": spec["speed"] = 60` —— HTTP/AOI 技能多带个 `speed` 会被用户当场指出 ✗

## 五、重启与单实例 (GUI 改码必须重启才生效)

- **杀进程别只杀 bash 包装**: 以 `bash -c "... python studio.py"` 启动时,
  `ps -eo pid,cmd | grep studio | awk '{print $1}' | head -1` 拿到的是**包装 bash**;
  杀了它 python 子进程还活着 → 再起一个 = **双开**(用户面前出现两套界面/两份日志)
- 正确取 PID: `ps -eo pid,cmd | grep "gui-venv311/bin/python studio[.]py" | grep -v grep | awk '{print $1}'` (取 python 那行), 起完 `ps | wc -l` 确认只剩 1 个 python
- **`pkill -f <模式>` 在任何脚本里都可能匹配到调用它的 shell**(即使写了 `[.]` 规避) → 最稳是**列 PID 逐个 kill**, 或写个小 .py 用 `os.kill(pid, ...)` 并排除自身 pid
- 重启后必须做的两件事: ① `ps` 查单实例 ② 用 offscreen 冒烟确认新代码能构造(别把崩的代码留在用户桌面上)

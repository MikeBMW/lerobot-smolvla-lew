# 控制台按钮 → 浏览器页: 精确做法与取证

适用: PyQt 控制台(`studio.py` / `simulink_module.py`)里"点按钮 → 开一个浏览器大图页", 页由本机
`cam_live_stream.py` 提供(叠加页 `:8791/overlay`、工位总览 6 路 `:8793/station`)。

## 1. 开窗的可用形状(实测: 点击 → 页面搬屏并最大化 = ~2s)
```python
def open_page(url, title_key, profile_name):
    import shutil, subprocess
    geo = None                                   # 页面该落在"控制台那块屏"
    for ln in subprocess.run(["wmctrl", "-lG"], capture_output=True, text=True).stdout.splitlines():
        if "XSpace Studio" in ln:
            p = ln.split(None, 7); geo = tuple(int(x) for x in p[2:6]); break
    # ① 已有同类窗口 ⇒ 搬屏+最大化+置前, 直接返回(秒回, 不重开)
    ex = [ln.split(None, 1)[0] for ln in subprocess.run(["wmctrl", "-l"], capture_output=True,
          text=True).stdout.splitlines() if title_key in ln]
    if ex:
        for w in ex:
            if geo: subprocess.run(["wmctrl", "-i", "-r", w, "-e", "0,%d,%d,%d,%d" % geo])
            subprocess.run(["wmctrl", "-i", "-r", w, "-b", "add,maximized_vert,maximized_horz"])
            subprocess.run(["wmctrl", "-i", "-a", w])
        return True, "复用已在的窗口"
    # ② 独立 profile 起新实例: profile 必须在 snap 可写目录
    snap = os.path.join(os.path.expanduser("~"), "snap", "chromium", "common")
    prof = os.path.join(snap, profile_name) if os.path.isdir(snap) else \
           os.path.join(os.path.expanduser("~"), ".cache", profile_name)
    os.makedirs(prof, exist_ok=True)
    flags = ["--new-window", "--start-maximized", "--user-data-dir=" + prof,
             "--no-first-run", "--no-default-browser-check"]
    bf = open("/tmp/zmax_page_browser.log", "ab")       # ③ 浏览器输出留证
    subprocess.Popen([shutil.which("chromium")] + flags + [url], stdout=bf,
                     stderr=subprocess.STDOUT, start_new_session=True)
    log("浏览器已启动, 页面加载中(最多 12s)")
    # ④ 认窗: 记下已有 id → 只认"新出现的 id 且标题匹配" → 40×0.3s, 每 3s 报一次进度
    seen = {ln.split(None, 1)[0] for ln in wmctrl_l()}
    for i in range(40):
        time.sleep(0.3)
        if i and i % 10 == 0: log("还在等浏览器窗口… 已等 %.1fs (地址 %s)" % (i * 0.3, url))
        wins = [ln.split(None, 1)[0] for ln in wmctrl_l()
                if title_key in ln and ln.split(None, 1)[0] not in seen]
        if wins: break
    # ⑤ 搬屏 + 最大化 + 置前(各 2 轮) → 读回 wmctrl -lG 几何写进日志
```
- `--start-maximized` 在本机 GNOME 下**不生效** ⇒ 必须 wmctrl 补一刀。
- `wmctrl -i -r` 要的是**窗口 id(第 1 列 0x…)**: 把标题当 id 传会静默无效, 日志却写"已最大化"。
- 判断"在哪块屏": 窗口 `x` 与控制台 `x` 差 <200 即同屏(本机笔记本屏 132 / 外接屏 3884)。

## 2. "没有新窗口"的两条真根因(按序排查)
1. 浏览器日志出现 `Failed to create .../SingletonLock` 或 `Failed to create a ProcessSingleton for your
   profile directory` ⇒ profile 目录 snap 写不了(放到了 `~/.cache`) ⇒ 换 `~/snap/chromium/common/<name>`。
2. 日志干净、进程也在, 但 `wmctrl -l` 始终没有新窗 ⇒ 请求被**已有实例**吞成后台标签 ⇒ 加独立 profile。

## 3. 取证: 别靠自报日志, 用离屏直调 handler + 窗口几何
```
DISPLAY=:0 QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/verify_<page>_button.py
```
脚本形状(参考 `tools/verify_station_button.py`): `SM.SimulinkModule()` → 清场(先关掉已有同类窗, 保证是
冷启动) → 连 `m.log_signal` 收日志 → `m.open_<page>()` → 轮询等日志出现"已打开 / 没能打开" → 断言:
① 目标 URL 真返 200 且页面含预期元素 ② `wmctrl -lG` 出现**调用前没有的**窗口
③ 该窗几何 ≈ XSpace Studio 那块屏(容差 40/60px) ④ 日志有"浏览器已启动 + 已打开"。
- `self._log()` 的行**到不了** `log_signal` ⇒ 断言别去匹配它; 控制台日志面板内容也**不在**
  `/tmp/studio_launch.log` 里 ⇒ 要留证就自己写文件, 或让用户贴面板原文(他贴的原文是最快的定因依据)。
- xdotool 点运行中的控制台按钮**不可靠**: 未聚焦窗口的第一次点击常被用于激活, 悬停出 tooltip 只证明指针位置。
  主证据用离屏直调 + 几何; 需要真实例行为时请用户点一次并把日志面板贴回来。

## 4. 页面别被"漏参数"搞丢
- `cam_live_stream.py` 的总览页要 `--station-port 8793` 才存在; 任何**自动拉起视频流**的按钮/脚本漏了这个
  参数 ⇒ 新起的流只服务 `/overlay`, `8793/station` **404** ⇒ 用户报"那个网页搞丢了"。改拉流命令必带上它。
- 拉流重启别用 `pkill -f cam_live_stream.py`(会打死调用它的那条命令自身), 按端口找 pid。
- 高频页面入口给两处: 控制台工具栏按钮 + 叠加页顶部链接(互为兜底)。

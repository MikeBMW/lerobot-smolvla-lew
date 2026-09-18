# 控制台重启收口 + 版本迭代发版（2026-09-18 实测沉淀）

## 一、重启控制台：先分清是哪个实例（双开坑）

`systemctl --user restart zmax-studio` **只能杀掉 service 自己的进程**。用桌面图标 / 终端起的实例活在
Gnome 会话 cgroup 里，restart 杀不掉 ⇒ **双开，而且用户看到的那个窗口还是旧码**
（本轮实测：restart 后 `wmctrl -l` 里窗口标题仍显示旧版本号，两个 studio.py 同时存在）。

```bash
ps -eo pid,etime,cmd | grep "studio\.py" | grep -v grep
cat /proc/<pid>/cgroup    # app.slice/zmax-studio.service        = systemd 服务实例（新）
                          # session.slice/org.gnome.Shell@x11.service = 桌面会话实例（旧，restart 杀不到）
kill -TERM <桌面实例pid>   # STEP1 先收掉旧实例（SIGTERM 会走它的 closeEvent 做 WS 清理）
systemctl --user start zmax-studio   # STEP2 再起服务实例（Restart=no，不自拉，必须显式 start）
DISPLAY=:0 wmctrl -l | grep XSpace   # STEP3 核窗口标题里的版本号 == 本次迭代版本
```
配套事实：`Restart=no`（反复重启被老倪叫停）· 无 autosave → 重启丢界面状态，输入图像窗口要重新点开。

## 二、版本迭代（中版本 = 次版本号 +1）的 5 个同步点

以仓库 `VERSION.md` 为准，缺一处就会"版本号不一致"：
1. `tools/gui/studio.py` —— 品牌版本小字 `ver = QLabel("Z-MAX vX.Y.Z")` + **两处** `setWindowTitle(... vX.Y.Z ...)`
   （其中一处带 `⚠️非调试模式`）+ **变更摘要首条注释**（写在最新条目之前，`# vX.Y.Z: …`，按「做了什么 + 根因」写）
2. `tools/gui/update_checker.py` —— `CURRENT_VERSION = "vX.Y.Z"`
3. `tools/gui/version_sync.py` —— `zmax_ver = "X.Y.Z"`（不带 v）
4. `tools/gui/docs_sync.py` —— `"version"` 与 `"zmax_version"` 两键
5. `VERSION.md` 版本历史表新增一行（放最前）

改完自检：
```bash
python3 -m py_compile tools/gui/studio.py tools/gui/update_checker.py tools/gui/version_sync.py tools/gui/docs_sync.py
grep -rn "v<旧版本>" tools/gui/studio.py tools/gui/update_checker.py tools/gui/version_sync.py tools/gui/docs_sync.py | grep -v "变更摘要"
```

## 三、发版（tag 触发双平台）

```bash
git add -A && git commit -F <msgfile>        # 大文件(权重/zip/pdf)不进库
git push origin main
git tag -a vX.Y.Z -m "..." && git push origin vX.Y.Z    # 触发 build-win-exe.yml（Windows .exe + macOS .app）并自动上传 Release
```
- 跑完必须做**资产实测验证**（不能只看 CI 绿）：sha256 对 GitHub digest、mac 主 app plist 的
  `CFBundleShortVersionString/CFBundleVersion`、Mach-O 是否 arm64、exe 的 PE `FileVersion/ProductVersion`。
  **三个误判坑（截断文件 / mac 包 16 个 plist 取错 / onefile 资产名非明文）见技能 `github-actions-ci`。**
- 历史既有红（与本版无关）：`docker-console.yml` 挂在 ACR 登录、`ci-cd.yml` 挂在 Simulink 合规检查
  → 判"是不是我引入的"要先看该 workflow 的历史 run 结论（每个 tag 都红 = 既有）。

## 四、时钟回拨会冻住控制台的新鲜度/自愈

GUI 判新鲜度用 `now - 文件 mtime`，NTP 回拨 8h 后 mtime 落在未来 ⇒ 帧龄为负 ⇒ **旧帧被判"新鲜"**（画面冻住不报警）；
断流自愈（6s 无新帧→自动重连）同样变恒假 ⇒ 冻住没人救。修法与扫查清单见
`unattended-pipeline-supervision/references/clock-step-freezes-daemons-and-freshness.md`。
纪律：**节拍/新鲜度一律 `time.monotonic()`，`time.time()` 只用于落盘时间戳**；帧龄钳非负、未来 mtime 拒用。
回归自检：`tools/verify_clock_skew_guard.py`（全绿才算修好）。

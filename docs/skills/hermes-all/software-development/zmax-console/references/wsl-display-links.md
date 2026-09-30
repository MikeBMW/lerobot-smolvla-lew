# WSL 显示 / 打开链接 / 弹窗样式 / 画布布局 铁律 (2026-08-12 修正)

## 1. 窗口不显示 / 飞屏 → XLaunch(VcXsrv) 是主显示链路 (2026-08-12 实测)
- **症状**: 用户说"控制台没打开", 但 `pgrep -af studio.py` 进程活着;
  `xdotool search --name "XSpace Studio"` 能搜到窗口, 但
  `getwindowgeometry` 位置 = `Position: -32692,-32650` (Xwayland 虚拟坐标系 bug,
  接近 -32768 16 位边界) → 窗口在屏幕外, 用户看不到。
- **用户真实显示链路 = Windows 侧 XLaunch (VcXsrv)**, 不是 WSLg wayland。
  2026-08-09 的 wayland 方案 (下方旧方案) 只能算备选, 08-12 复现 WSLg 下窗口
  仍落屏幕外。
- **xdotool windowmove 无效** (wayland/xcb 下 WM 拦截位置, move/activate 不动),
  别浪费时间在移动窗口上, 直接切 XLaunch。

### 排查三连
1. 进程活着? `pgrep -af studio.py`
2. 窗口在哪? `xdotool search --name "XSpace Studio" getwindowname %@; xdotool getwindowgeometry <WID>` → 负坐标 = 屏幕外
3. XLaunch 状态? `tasklist.exe | grep -i vcxsrv` → **vcxsrv 可能是僵尸进程** (进程在跑但显示失效, 光点开 XLaunch 没用, 必须杀重启)

### 修复配方 (bash 里 taskkill.exe //F //IM 参数翻译报错 → 一律用 PowerShell)
```bash
# 1) 重启 XLaunch: -ac=关访问控制 (X0.hosts 只有 localhost, 不关 WSL 连不上);
#    -multiwindow=每窗口独立 Windows 窗口
powershell.exe -NoProfile -Command "Stop-Process -Name vcxsrv -Force -ErrorAction SilentlyContinue; Start-Sleep 1; Start-Process 'C:\Program Files\VcXsrv\vcxsrv.exe' -ArgumentList ':0','-ac','-multiwindow','-clipboard','-wgl'"

# 2) 验证端口 (NAT 模式: Windows 主机 IP = ip route 的 default via, 如 172.18.80.1)
GW=$(ip route | awk '/default/{print $3}')
timeout 3 bash -c "cat < /dev/null > /dev/tcp/$GW/6000" && echo PORT_OK

# 3) 用 XLaunch 启动 GUI (DISPLAY=主机IP:0 走 TCP 6000, 不是 WSLg socket)
DISPLAY=$GW:0 /usr/bin/python3 tools/gui/studio.py
```
- 验证: `DISPLAY=$GW:0 xdotool search --name "XSpace Studio"` + getwindowgeometry
  位置应正常 (实测 60,40 / 1400x900)。
- 旧 vcxsrv 必须 Stop-Process 杀掉 (僵尸不杀, 新实例起不来或端口被占)。

### 旧方案 (备选, 别当首选)
- `QT_QPA_PLATFORM=wayland` 曾解决过 xcb 飞屏 (2026-08-09);
  但 wayland 下 xdotool 查不到窗口, 无法定位/验证, 08-12 复现仍会屏幕外。
- EGL/ZINK 警告 (`MESA: error: ZINK: failed to choose pdev`) 是软件渲染提示, 可忽略。

## 2. WSL 打开网页 → cmd.exe start (Windows 浏览器)
- **坑**: `QDesktopServices.openUrl` 在 WSL 报
  `Unable to detect a web browser to launch 'https://...'` (WSL 无 xdg-open)。
- **正确**: `subprocess.Popen(["cmd.exe", "/c", "start", "", url])`
  → 用 Windows 默认浏览器打开 (studio.py 9489 已有同款: 工厂大屏链接)。

## 3. 深色主题弹窗 → 必须显式白字
- PyQt5 QDialog 默认继承系统 palette, 深色主题下 QLabel/QComboBox/QCheckBox
  **黑字看不清** (用户多次反馈)。
- 修复: dialog.setStyleSheet 统一覆盖:
  ```
  QDialog { background:#0d1117; }
  QLabel { color:#e6edf3; }
  QComboBox { background:#161b22; color:#e6edf3; border:1px solid #30363d; }
  QComboBox QAbstractItemView { background:#161b22; color:#e6edf3; selection-background-color:#0d3b33; }
  QCheckBox { color:#e6edf3; }
  QPushButton { background:#21262d; color:#e6edf3; }
  ```
- 选中高亮: `background:#0d3b33; border:2px solid #00d4aa` (青绿场景主题)。

## 4. 模块库按钮序号 (LIBRARY_SEQ) — 删除后重排
- 模块库按钮 tooltip = `VEH.5.{LIBRARY_SEQ}` (LIBRARY 列表序, 动态重排)。
- **删除任意按钮后, 后续按钮序号全部前移重排** —— 用户看到 "13 号按钮还在"
  其实是**新的按钮顶上了 13 号位**, 不是没删。必须主动解释, 别反复删错。
- 用户窗口若一直显示旧内容: 先查进程 (唯一实例) + 版本, 窗口缓存问题重启解决。

## 5. 场景 node 交互 (用户明确偏好)
- **双击场景 node = 只打开 3D 链接, 不建子模块** (用户原话: "不需要打开子模块, 只要打开链接")。
- 场景链接映射: SCN-01→scene-3d.html?scene=insert, SCN-02→handle, SCN-03→aoi。
- 模块库场景按钮 (静态 LIBRARY + 动态数据集分组后) 同样只打开链接。

## 6. 画布布局 — 留间距零重叠
- 原子技能全场景一键建链 (open_atomic_skill_flow):
  - 技能节点间距 **90** (节点高 50, 空隙 40)
  - 场景行距 **680** (容纳最多 7 技能 × 90 = 630, 不跨行重叠)
  - 结构条件对齐技能列中部; SYS1 共用 1 个; 后接 A001~A010 动作输出 + 📤 Action 汇总。
- **验证**: offscreen 遍历所有节点坐标, 断言 `abs(x1-x2)<100 and abs(y1-y2)<60` 的重叠对 = 0。

## 7. 场景 node 小机器人图标 (QPainter)
- scene 类型节点 paint 分支画青色小机器人 (右上角):
  天线(竖线+圆点) → 圆角矩头 → 2 眼睛点 → 身体圆角矩 → 2 手臂线。
- add_node icon 映射: `"scene": "🤖"`。

## 8. web 分身协作注意
- web (4090) 负责场景 JSON / 前端页; 我 (4060/WSL) 负责 Simulink 集成 + ECS 部署。
- web 的 4090/V100 ssh 密码会失效 (`Permission denied (publickey,password)`) ——
  不能依赖从 GPU 机器拉文件; 文件缺失时自己写等价物 (如 scene-3d.html) 部署 ECS。
- ECS 部署后必须 `chmod 644` (nginx 403 坑)。

## 9. scene-api.php POST 端点 (场景 JSON 传 ECS, 2026-08-09 验证)
- **web 说"端点就绪"可能实际 404** (只发了方案没部署) —— 先 `urllib.request` 实测 POST,
  404 就自己写 PHP 部署 (flows/scene-api.php, 2200B)。
- PHP 端点部署三步: scp → `chmod 644` → `mkdir scenes && chown www:www scenes`
  (**php-fpm 跑在 www 用户**, root 建的目录 755 → `file_put_contents` Permission denied → HTTP 500)。
- 500 排查路径: 宝塔 nginx 错误日志 `/www/wwwlogs/<domain>.error.log`
  (`FastCGI sent in stderr: "PHP message: PHP Warning: ..."` 直接给根因)。
- 端点形态: `POST scene-api.php/<insert|handle|aoi>` (PATH_INFO 由 nginx fastcgi 自动解析,
  PHP 里 `basename(parse_url(REQUEST_URI, PHP_URL_PATH))` 取 type), 带 CORS `Access-Control-Allow-Origin: *`。
- payload 格式 (web 约定): `{"name","skills":[工序名列表],"specs":{"success_rate":0.995(小数),"cycle_time":3.5},"kpi":{全指标}}`;
  数值解析用正则取首数字 `\d+(\.\d+)?`, success_rate>1 时 `/100` 转小数。
- 保存路径: `/www/wwwroot/datadrive.world/scenes/scene_{type}.json` (chmod 644, 页面实时加载)。

## 10. 原子按钮交互演进 (用户真实流程, 2026-08-09)
- v1 选技能弹窗 → v2 场景优先+推荐勾选 → **v3/v4 一键全建** (用户最终要: 点原子按钮
  → SCN-01/02/03 三场景全链直接上画布, 不弹选择框)。
- 最终结构: 3 场景各自 (场景node→atoms技能序列→结构条件) → **3 结构条件汇聚 1 个共用 SYS1**
  → SYS1 后接 **A001~A010 动作输出节点群** + 📤 Action 汇总 (用户: "A00~A10全都是系统1的输出")。
- 场景清空重建前弹确认 `_qmsg_yes`; 建链期间 `_sync=lambda:None` + `_suspend_undo` 防卡顿, finally 恢复。

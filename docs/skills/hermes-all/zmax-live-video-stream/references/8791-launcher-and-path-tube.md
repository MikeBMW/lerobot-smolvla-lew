# 8791/8793 推流必须用正规启动器（踩过的坑）

**一律用**：`bash /home/ubuntu/zmax_rel/tools/start_station_stream.sh`（自带：按卡名+能力解析相机设备、抬 fd 上限、按端口停旧实例）。

**不要**自己拼 `cam_live_stream.py` 的命令行重启。少一个开关就是一条功能整线消失，而且报错点离根因很远：

| 缺的开关 | 现场症状 |
|---|---|
| `--overlay --overlay-src all --overlay-fps 10` | `/snapshot/overlay_arm.jpg` 一直 **503「该路还没有帧」**，`/stats` 里 **根本没有 `ov_arm`/`ov_local` 键**；叠加管道路径/检测框全不见（原帧 `/snapshot/arm.jpg` 与 MJPEG 仍正常 ⇒ 很容易误判成"相机/网络问题"） |
| `--ctl-motion` | 启动输出写「手动控制: 仅演练(dry-run)」⇒ 页面手动控制变成演练，**不真动** |
| `--station-port 8793` | 工位总览端口起不来 |

**如何快速区分**：`curl -s 127.0.0.1:8791/stats` —— 正常实例的 JSON 里 **同时**有 `arm/local/local2/depth/ov_arm/ov_local...`；如果只有 `arm`+`depth`，就是叠加产线没起。

**教训**：
- 从 `/proc/<pid>/cmdline` 抄命令行重启**不可靠**（现场可能存在多个同名实例/被别处接管，同一 pid 的 `ps` 参数与 cmdline 可能不一致）⇒ 先找**启动器/unit/文档**，再动手。
- 重启**现场在用的服务前**先 `ls tools/*start*.sh`、`grep -rl <服务名> docs/` 找正规入口，并先备份其启动参数。
- 停自己的服务用括起写法（`cam_live_strea[m].py`），否则 `pkill -f` 会匹配自身命令行把自己杀掉。

# 轨迹的三维可读渲染（管道）

`tools/scene_overlay.py` 的 `draw_path_tube`（2026-09-29 加入，commit 7e0ccb62）：origin=plan/trace 的 `kind=path3d` 点按**管道**绘制：
- 线宽随该点投影深度变化（默认 3~14px，近粗远细）⇒ 必须有透视感才读得出三维
- 每 10 个路点画一个**截面环**（切面椭圆 + 法向十字刻度），末端必补一环
- 管体三档亮度（主色 ×0.55 暗面 / ×0.22 暗边 / 原色高光带）+ 端点圆帽
- 长轨迹先铺底、短路径后画，否则 400 点的 trace 会把 7 点的 plan 盖死
- 只改渲染：`ORIGIN_STYLE` 键、`box3d`/`box` 字段语义一律不动；无 pts3d 时行为与原来一致（不画）

**注意**：管道由 `cam_live_stream.py` 在**启动时 import 一次** `scene_overlay` ⇒ 改完渲染**必须用启动器重启 8791** 才生效（离线渲染验证可以先绕过重启）。

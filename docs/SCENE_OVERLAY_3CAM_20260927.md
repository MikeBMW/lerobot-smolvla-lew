# 场景叠加 · 三相机并存改造（2026-09-27）

老倪口径：场景叠加里要兼容三个摄像头 —— ①机器人手臂相机 ②笔记本内置摄像头 ③MAXHUB 电视顶部摄像头。
另问：`http://10.163.146.78:8791/overlay` 这个链接哪来的？

---

## 一、三相机现状（全部实测，非声明）

| 逻辑源名 | 物理相机 | 设备 | 取流方式 | 实测 |
|---|---|---|---|---|
| `arm` | 机器人臂上 D405（Orin） | 远端 | HTTP `192.168.23.66:8792/frame.jpg` | 640×480 · 帧龄 1.4s · 亮度 102 |
| `local` | 笔记本内置 | `/dev/video2` = `Integrated RGB Camera` | V4L2 直读 | 640×480 · 帧龄 0.08s · 亮度 114 |
| `local2` | MAXHUB 电视顶摄 | `/dev/video0` = `WT15: MAXHUB-Camera` | V4L2 直读（也支持 `--local2-url rtsp://…` 走网络） | 1280×720 · 帧龄 0.05s · 亮度 113 |

启动命令（画布按钮自动用同一条）：

```
tools/cam_live_stream.py --port 8791 --quality 72 --fps 30 \
  --arm-http http://192.168.23.66:8792/frame.jpg --arm-fps 30 \
  --local-dev 2 --local2-dev 0 \
  --overlay --overlay-src all --overlay-fps 10
```

- **相机身份不再靠参数名猜**：服务读 `/sys/class/video4linux/videoN/name`，随 `/stats` 下发 `label`，
  页面与画布直接显示真实相机名。（之前 `--local-dev 0` 映的其实是 MAXHUB，页面上却写“笔记本相机”。）
- MAXHUB 那路既能 USB 直读，也能换成网络流：`--local2-url rtsp://…` 或 `http://…/video`（`http(s)` JPEG/MJPEG 直转，不重压）。
- **真几何投影只对臂上相机成立**（只有它有手眼标定）；笔记本内置 / MAXHUB 两路没有手眼，
  生成“仿真/场景”框时**如实拒绝**，只有纯 2D 来源（YOLO 检测 / 大模型理解）三路都能跑。

## 二、端点（加源不再改路由表）

正则通用路由 —— `^/(overlay/)?<name>.mjpg$`、`^/snapshot/(overlay_)?<name>.jpg$`，
`/stats` 按实际存在的源动态枚举 ⇒ 以后接第 4 路相机只加 worker 与参数。

| 端点 | 说明 |
|---|---|
| `/arm.mjpg` `/local.mjpg` `/local2.mjpg` | 三路原始流 |
| `/overlay/<源>.mjpg` | 三路叠加流（检测框/大模型框/仿真框 + 真值带） |
| `/snapshot/<源>.jpg` · `/snapshot/overlay_<源>.jpg` | 单帧（画布/手机取帧用，实测 0.8ms） |
| `/stats` | 每路 `online/fps/帧龄/压缩比/label` |
| `/gen?kind=sim\|vlm\|det\|scene&cam=<源>` | 按相机生成框（`sim/scene` 只对 `arm` 有效） |
| `/overlay` | 叠加页（三个相机按钮 + 双图直方图） |
| `/app` | 手机版叠加页（臂上 / 笔记本内置 / MAXHUB 顶摄 / 双路） |

## 三、画布上直接出三路画面

「🧩 场景叠加」按钮 → 画布节点 **🎥 真实场景叠加 · 双眼** 显示一张 **2×2 拼图**（572×344）：
每格一路相机，逐格标 `相机名 · 框数 · 真值链 OK/断 · 规格龄`，顶部真值带标**每路实时帧龄**；
取不到帧的路在带上标 `未接: xxx`（不画假画面）。节点自动放大到 580×350，放大前做重叠检查。

## 四、`http://10.163.146.78:8791/overlay` 是哪里来的

来自控制台自己的代码，不是外部给的、也不是站点上的页面：

1. `tools/gui/simulink_module.py` 的 `open_scene_overlay()`（「🧩 场景叠加」按钮 handler）
   用 socket 连 8.8.8.8 取本机 LAN IP → 拼成 `http://<本机IP>:8791/overlay`；
2. `8791` 是 `tools/cam_live_stream.py` 起的视频流服务端口（HTTP）；
3. `/overlay` 是该服务的叠加页路由；
4. IP 部分是 `wlp0s20f3` 的 DHCP 地址（当时代码取到 10.163.148.36，日志打的就是这个；
   06:54 NetworkManager 重租成 10.163.146.78，所以你手上那个链接是**新地址**）。

⚠️ 该 IP 会随 DHCP 变。以后要看：页面地址以**按钮日志里的那一行为准**，或直接用本机
`http://127.0.0.1:8791/overlay`；手机用 `http://<本机当前IP>:8791/app`。

## 五、诚实边界

- `arm` 路偶发上游超时（Orin `8792/frame.jpg`），此时臂上格会显示较旧的一帧，**帧龄在带上如实标出**（不藏）。
- 笔记本内置 / MAXHUB 两路**无手眼标定** ⇒ 只有 2D 框（检测/大模型），没有真几何投影框。
- `ss_geom_calib` 仍未采集、手眼旋转 915° 异常 —— 与本次三相机改造无关，仍是既有缺口。

## 六、取证脚本

- `tools/verify_three_cameras.py` —— 六路快照可取（JPEG 标志 + 叠加差异像素 %）+ 页面按钮 + 通用路由。
  实测：arm 差异 58.5%、local 17.2%、local2 12.2%；三页按钮齐全；未知源返回 503（端点活着）。
- `tools/verify_three_cam_canvas.py` —— 画布拼图逐格取证（尺寸 572×344、逐格 std/近黑占比、格子互不相同），
  落盘 `/tmp/canvas_3cam.png`。实测三格 std 73.7/70.5/62.7，近黑占比 ≤1.4%。

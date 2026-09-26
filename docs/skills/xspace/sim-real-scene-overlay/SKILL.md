---
name: sim-real-scene-overlay
description: "Use when 要把仿真的3D物体/检测框叠加到真机视频流上, 或做深度建图/手眼正投影验证。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [overlay, handeye, projection, depth-map, ros, video-stream, verification, zmax]
    related_skills: [real-arm-handeye-calibration, real-arm-motion-control, state-space-canvas-engineering, robot-vision-3d-localization]
---

# 真实场景叠加 / 仿真↔真机几何投影

## When to Use
- 用户要"把仿真场景的边界框叠到真实视频流上""虚拟场景与真实场景叠加""同步渲染"。
- 需要把 base 系 3D 点/盒投到真机相机像素（或反向：像素 → base）。
- 要做真实深度建图（深度 + 手眼 → base 系点云/语义物体）。
- 验证手眼外参到底准不准（**正投影**比旋转法向检验靠谱得多，见下）。

## 核心: 一条链, 三个参数, 全实测
```
p_base --(实时 TCP 位姿真值)--> p_tcp --(手眼 X=T_cam2tcp)--> p_cam --(内参 K)--> (u,v)
```
```python
def base_to_px(P_base, K, X_cam2tcp, tcp7):   # tcp7=[x,y,z,qx,qy,qz,qw] base系 m
    R_g, t_g = quat_to_R(tcp7[3:7]), tcp7[:3]
    R_x, t_x = X[:3,:3], X[:3,3]
    P_tcp = (R_g.T @ (P_base - t_g).T).T
    P_cam = (R_x.T @ (P_tcp - t_x).T).T
    z = P_cam[:,2]                      # z<=0 的必须丢(相机背后), 否则投出幻影框
    return np.stack([K["fx"]*P_cam[:,0]/z+K["cx"], K["fy"]*P_cam[:,1]/z+K["cy"]],1)
```
3D 盒 → 2D 框：8 角点全投，取 min/max；**角点 x/z 只有 4 个有效时就不要画**（近平面劈开）。

## 内参按**流的分辨率**选, 不能换算
D405 的 1280×720 与 640×480 是**不同 FOV**（不是 2× binning）：
655.06/640 = 1.02 vs 394.06×2 = 788 ⇒ 720p 视角更宽。用错分辨率内参 ⇒ 主点错位。
`ros2 topic echo --once /realsense/color/camera_info` 取真值，别信记忆里的数。

## 验证: 正投影 vs 图上实检（首选, 比旋转检验强）
用**已知 base 位置的点**（标定板中心由多姿势闭环解出）**逐位姿**投回**该位姿自己的图**，
和该图实检的质心比。实测 8 位姿：**中位 5.2px ≈ 3.1mm**，最差 9.9px（斜视角位姿）。
- 口径必须同源：解算器闭环若用 `OBJ.mean(0)`（20 点质心），比对面也得取**实检点云质心**，
  不能比"图案原点" —— 否则差一个 68mm/40mm 的常量偏移，看起来像"算法错"。
- **闭环一致性(std) ≠ 旋转正确**，两者要分开取证。旋转精度想单独看，用板面法向投 base 系判
  偏离竖直多少（小角度好、斜视角 PnP 本身不可靠）。
- 双链收敛是最强证据：
  · `det` 链（纯图像）YOLO 实检框中心
  · `sim` 链（纯几何）深度 3D → 手眼 → 投影框中心
  实测中心差 **2.1px**（215mm 处≈1.1mm）⇒ 证明投影是真几何而不是画上去的。

## 视频流叠加的工程做法
- **独立渲染线程 + 独立帧槽**，只在开启叠加时才付出"解码→画→重编码"开销；
  原来的"JPEG 直转"最快路径**一字不改**（多条 RTSP/MJPEG 消费者的实况流禁不起往里塞 decode）。
- 规格文件（几 KB JSON）**每帧重读** ⇒ 外部生成器一写就生效，服务不用重启。
- 规格按 **provenance 分源**（sim/vlm/det），生成器**只替换自己那一类**（`merge_origin`）；
  若整体覆盖会把别的来源框冲掉。
- TCP 位姿**按 2s 缓存**：投影要实时位姿，但读 Orin 有开销，不能每帧读。
- 画面里必须画**真值带**（帧龄/时间/TCP/手眼/框统计）——不然无法自证状态，且用户会把画面当结果。

## 深度建图（容器内跑 ROS 只读订阅）
```
深度像素 + z=值×depth_scale → p_cam → p_tcp → p_base → 体素/占据栅格 + 语义物体 3D
```
- 语义物体的 3D **取框内中位深度**（不是单点）：物体表面深度近似恒定 ⇒ 天然抗单点噪声和边缘空洞。
- 物体尺寸没有就先用标称值并在产物里 `note` 写清"尺寸用标称值，朝向未估"。
- 点云别用来做验收包围盒：远场噪点（量程 3.5m）会把 bbox 拉到米级，要报分位数。

## Pitfalls
| 坑 | 症状 | 修法 |
|---|---|---|
| `/robot/tcp_pose` 当 `Pose` 订阅 | depth/info 都有、tcp 恒 None | 它是 **`PoseStamped`**，位姿在 `.pose` 下 |
| 用状态码判端点真假 | 任意路径都 HTTP 200 | 看**响应头字节**：`FFD8`=JPEG 回退、`\x93NUMPY`=真 npy |
| 容器里想写仓库 | 静默不落盘 | `/repo` 常是 **ro**；产物写 `/out`，读取侧两处都找 |
| `findCirclesGrid` 检不出 | 板明明在 | 裁剪板区 → 放大 2.2x → **反相** → `ASYMMETRIC` 4×5 → 回全图坐标配全图内参 |
| 推理型 VLM `content` 空 | 框提取不到 | `max_tokens` 给 9000（reasoning 吃光额度）；content 空时退 `reasoning_content` |
| 大模型框越界 | 画出莫名长条 | 落图前强制 clip 到画面 + 丢弃退化框（<3px） |
| 拿仿真世界系几何直接投 | 框飞到天涯 | 仿真世界→base 需**示教几何标定**；没有就用深度实测的 base 系 3D 当物体源 |

## 交付前自检（必做）
1. `--verify` 投影链自检（手眼 det/正交性/闭环 std）
2. 正投影 vs 实检逐位姿表（报中位 + max，不报单个最好）
3. 双链收敛 IoU/中心差
4. 叠加帧与原帧**差异像素占比**（证明真画上了，不是只报了个数）
5. 把叠加后的图**再喂给 VLM 回读**，核对它读到的底部真值带内容 = 实际状态
6. 服务端点 HTTP 状态 + `/scene.json` 的 `_overlay_info`（画几框/跳过原因/tcp_ok）

## 参考实现
`zmax_rel/tools/scene_overlay.py`（投影+绘制+规格）· `gen_overlay_from_vlm.py` · `gen_overlay_from_det.py` ·
`ros_scene_depth_build.py`（容器内深度建图）· `verify_projection_chain.py` · `verify_overlay_alignment.py` ·
`cam_live_stream.py --overlay`（端点/叠加页）· `docs/SCENE_OVERLAY.md`（完整交付文档）。

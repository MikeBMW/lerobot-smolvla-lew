# 采集 schema / 位姿数学 / 导出约定

## frames.jsonl 每行(采集器 `tools/gs_capture.py` 落)
```json
{"seq":0,"t_wall":1790808058.7,"t_mono_fetch0":12345.6,"t_mono_fetch1":12345.603,
 "fetch_ms":2.4,"pose_before":{…},"pose_after":{…},"pose_t_gap_ms":2.4,
 "file":"frame_000000.jpg","bytes":27096}
```
- 配对: 取 `pose_after`(失败则 `pose_before`), 认为它代表 `[t_mono_fetch0, t_mono_fetch1]` 这一瞬的 TCP; 两者差大(运动中)= 取图中点位姿更准, 可线性插值。
- `t_wall` 只留档; **一切排序/配对用 `t_mono_*`**。
- 图**原样存**(Orin 已压好 JPEG), 不要解码再压 —— 3DGS 输入别叠加一层重压损失。

## 位姿字段(rokae `tcp_out/latest.json`)
`x,y,z`(m) + `rx,ry,rz`(**弧度**) + `qx,qy,qz,qw` + `frame:"base_link"` + `joint[12]` + `ts`/`t`。
- 四元数与 rx/ry/rz 同源(差 ≤1e-6 rad, ZYX), 用**四元数**建旋转矩阵(避免欧拉奇异)。
- 位姿源静止时仍按 50Hz 写同一值 ⇒ 别拿“值在变”当“臂在动”; 判动看 `capture_summary.json` 的 `pose_*_range_mm`。

## 相机外参(重建的输入)
```
T_base_tcp = [R(qx,qy,qz,qw) | (x,y,z)]     # 来自 latest.json
T_tcp_cam  = inv(T_cam2tool)                 # handeye_state.json 给的是 cam→tool
T_base_cam = T_base_tcp @ T_tcp_cam          # 相机外参
```
- 手眼残差(本机 0.06mm / 0.0046°)远小于 D405 在 7cm~1m 的像素级误差 ⇒ 不是瓶颈; 瓶颈通常是**内参 K、时间配对、过曝**。

## 导出给训练器
- **COLMAP 文本**(通用): `cameras.txt` = `CAMERA_ID PINHOLE W H fx fy cx cy`; `images.txt` = `IMAGE_ID QW QX QY QZ TX TY TZ CAMERA_ID NAME`。
  COLMAP 的 `(q,t)` 是 **world→camera**: `R_cw = T_base_cam[:3,:3].T`, `t_cw = -R_cw @ T_base_cam[:3,3]`。写反 = 场景镜像/直接崩。
- **nerfstudio transforms.json**(gsplat/nerfstudio 的 loader 也吃): `frames[]` 给 `file_path` + `transform_matrix`(是 **camera→world**, 即 `T_base_cam`) + `fl_x/fl_y/cx/cy/w/h`; 顶层 `applied_transform`/`scale` 保持单位阵/1。
- 训练前必查: 挑 3~5 个已知位姿, 把“单位矩阵代入”反投影一遍(把场景里一个已知点投到图上看着对不对), 比训完再猜便宜得多。

## 什么算“够用的一次扫描”
- 覆盖: 目标区域每个面至少 2~3 个不同方向看到(相邻帧重叠大); 单基线平移会“薄”。
- 帧量: 640x480 下 200~600 帧能干一个小工作区; 帧多不是好事——重复视角只增时间不加信息, 用位姿去重(位置+朝向阈值)筛。
- 质量筛选(可与 VLM 联合): 拉普拉斯/梯度能量判糊, 直方图全 255 判过曝, 帧间位姿跳变过大(运动中拖影)直接丢。

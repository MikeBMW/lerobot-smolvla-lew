# 🔌 数据总线 v2 增量 — 接口快照全链路 + 用户偏好 (2026-08-22 后半段)

（补充 data-bus-trace.md：以下是本会话后半段新增的经验）

## 接口快照必须对齐画布 links 拓扑 (用户"数据不全")

- `flows/state_space_obs.json` 的 `links` 是权威数据流。`_io_snapshot` 曾只记核心 9 模块,
  漏了感知层 (📦数据源→图像流→🎯YOLO→📐2D→3D→🧩obs + 🖐触觉 + 🔍AOI)。
- 铁律: `_io_snapshot` 的模块 = 画布 links 覆盖的**全部**节点, 从数据源到物理世界全链路。
- 补全后: 14 模块 / 51 接口 (感知层 5 + 核心层 9)。`SS_MODULE_TO_NAME` 也要补感知层映射。
- 引擎 `_io_snapshot` 加 `frame_id` 参数 (run 循环传 `step`)，感知层图像流用帧号模拟。

## fuse_sensors 真实输入 3 个 (用户"obs 无中生有")

`perception.py` `fuse_sensors(rgbd_feats, force_6d, tactile_marker)`:
- rgbd_feats = 39D 视觉结构（主输入，曾漏写）
- force_6d = 6D 力觉（仅接触检测用，**不进 obs**）
- tactile_marker = 4D 触觉
- obs = concat(rgbd_feats, tactile) = 43D
数据总线 in 要写全 3 个输入，否则输出像"无中生有"。

## 用户偏好 (老倪，硬性纠正)

- **数据列不要花哨着色**: 曾做"非零维度绿高亮/零维度灰弱化" → 用户"绿色太多看不清" →
  撤销，恢复统一白色。数据列就正常纯文本显示。
- **渲染图贴合数据语义**: 右键渲染 RGB-D 曾被画成"轨迹线+HUD 监控俯视图" → 用户"怎么是仿真波形图" →
  改 RGB 彩色图 + Depth 灰度图并排。渲染 = 数据物理语义的可视化，不是监控曲线图。

## 右键渲染 RGB-D 图片

- `model_tree.py` `render_rgbd_frame(tr, idx)`: 左 RGB 彩色场景（光模块金/孔位红/末端蓝）+
  右 Depth 灰度图（z 高度编码）。Pillow 渲染，主线程安全。
- 数据总线右键视觉信号行（接口名含 RGB-D/图像流/视觉/状态流/坐标/检测框）→
  菜单「🎨 渲染 RGB-D 图片」→ 弹窗（QDialog + QLabel 显示 QPixmap）。
- 行用 `QTableWidgetItem.setData(Qt.UserRole, t)` 存快照时间，渲染时 t→tr 索引定位帧。
- PIL→QPixmap: `img.tobytes("raw","RGB")` → `QImage(..., Format_RGB888)` → `QPixmap.fromImage`。

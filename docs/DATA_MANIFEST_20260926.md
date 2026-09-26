# 数据清单 (2026-09-26/27, 关机前)

> data/ 按 Git 精简规则不入库; 本清单入库, 便于重启后定位。

| 路径 | 内容 | 大小 |
|---|---|---|
| data/scene | 5 个文件 | 2.7M |
| data/selfcal | 8 个文件 | 68K |
| data/handeye | 89 个文件 | 333M |
| data/yolo_aoi_annot | 55 个文件 | 0 |
| data/selfcal | 8 个文件 | 68K |

关键文件:
  - data/scene/overlay_spec.json (3099B)
  - data/scene/objects3d.json (733B)
  - data/scene/dual_scene_20260926_155730.json (1822B)
  - data/scene/dual_scene_20260926_155730.png (1371495B)
  - data/scene/dual_scene_20260926_155656.png (1369246B)
  - data/selfcal/excite2_20260926_152930.json
  - data/selfcal/excite_20260926_145325.json
  - data/selfcal/reality_gap2_20260926_144825.json
  - data/selfcal/reality_gap_20260926_144636.json

臂位姿(关机前, 非我移动): TCP=(533.7, 231.3, 227.1)mm 静止 · 并行线做了手眼标定
版本: v5.15.13 (并行线冻结, 我的双眼叠加在 6eafe265/833806ec)

---
name: zmax-scene-engineering
description: Use when Z-MAX 场景工程化/原子技能/合作闭环. 场景JSON、3D链接、POST、row_bg坑。
---

# Z-MAX 场景工程化 (2026-08-09)

## 触发条件
- Simulink 场景 node / 原子技能场景 / 合作数据闭环画布
- scene-api.php POST / scene-3d.html 链接
- row_bg 背景布局问题

## 核心文件
- `flows/scene_skills_3scenarios.json` — 三场景权威数据源 (SCN-01插拔/SCN-02搬运/SCN-03检测, id/scene_id 双兼容, process_steps+performance)
- `flows/cooperation_closed_loop.json` — 合作合规闭环画布 (19节点14连线)
- `flows/scene-3d.html` — ECS 3D 场景页 (部署 datadrive.world)
- `flows/scene-api.php` — POST 接收端点 (保存 scenes/scene_{type}.json)
- `tools/gui/simulink_module.py` — open_scene_link / _open_scene / open_atomic_skill_flow

## 关键链路
1. 场景 node 双击 → `_open_scene` → JSON 上传窗口 (预览/链接/上传按钮/结果)
2. 上传 → POST `scene-api.php/<insert|handle|aoi>` (web 格式: name/skills/specs/kpi, success_rate 小数 0.995)
3. 打开链接 → `cmd.exe start` (WSL 无浏览器, QDesktopServices 报 "Unable to detect a web browser")
4. 原子按钮 → 一键建三场景全链 (3场景+20技能+3结构条件+1SYS1+11action = 38节点)

## 坑 (已踩)
- **row_bg 名字区**: 背景名画在左侧 8-134px 竖排居中, 长名截断 → 名字 ≤8 字, 节点 x ≥ 背景x+160
- **load_flow_file 连线字段是 f/t** (不是 src/dst), 节点 id 任意字符串, 类型必须在 NODE_TYPES
- **NODE_TYPES 缺 data 类型** → add_node KeyError 加载中断 → 已补 data (icon 📊 color #58a6ff)
- **scene-api.php 500 = scenes 目录权限** → chown www:www (php-fpm 用户)
- **技能间距**: 56px 重叠 → 90px (节点高50); 场景行距 680 (7技能×90=630)
- **SYS1 共用**: 三场景结构条件汇聚 1 个 SYS1, 后接 A001~A010 action 节点群 + 📤汇总

## 场景 ID 映射
- SCN-01 → insert (插拔/老化箱/QSFP28)
- SCN-02 → handle (搬运/料盘/12槽)
- SCN-03 → aoi (检测/7位/2μm)

## 验证
- offscreen: `load_flow_file` 后断言节点/连线数 + data×2 + row_bg×4
- 公网: `urllib` POST scene-api.php 3 端点 HTTP 200 + 保存文件可读
- base64 JSON 参数: b64u 可逆 + 页面含 renderJsonDesc

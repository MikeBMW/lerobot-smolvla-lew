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

## L4 抗干扰 90° 演示场景 (gen_l4_demo_*, 2026-09-10 全链打通)
- **GUI 档位语义 v5.5.5**: 档位三档 L2/L3/L4; L4 = 90° 演示全链 (点 L4 ▶运行 = RealStateSpaceSim demo_l4 → L4Demo ①转台90°→②绕z抓横→③治具回正→④标准抓取→⑤插入49mm→⑥拔出→⑦AOI→⑧光耦合η=1.0, success 3/3 ~5600步~3min); 旧 L4D 档并入 L4 (cap_level "L4D" 归一 "L4"); 真实 L4 自主恢复(±15°干扰重试) CLI/测试可达
- **Sawyer 臂可达区坑 (4段全败根因)**: metaworld 场景设备坐标必须实测可达 (servo 残差法: 探针 palm 至目标, 残差>几mm=不可达); (0.30,0.30) 不可达 (palm 卡 y≈0.40, 残差100mm → ④试抓全败/peg钉穿盘 Δz-0.011); 转台用 (0.42,0.60) 可达(3mm) 且避 AOI 视觉区(0.12,0.62); 改动 gen_l4_demo_scene.py turntable body pos + gen_l4_demo_video.py TURNTABLE_XY 必须同改
- **指垫中心 ≠ 手掌原点** (垫在掌 +Y≈0.105): 抓取伺服目标 = 抓握点 − 指缝偏置 (pc−pad_mid−palm), 否则指缝落模块外 10.5cm; 闭夹后用 d.contact 查 pad↔peg 真接触 (防钉夹假"成功")
- **钉夹 pin 必须世界系偏移**: rel_pos 在世界系测得 → 钉回 = hand_xpos + rel_pos; hx@rel 遇手基座 −90°Y 旋转把 z 搅进水平 → peg 钉穿盘面; ②③ 历史路径(hx@rel)勿动, 新段用 self._pin_world=True
- **ensure_scene() 前置**: GUI 引擎委托 (_run_demo) 与 gen main 出片前必须重生成场景 XML (真实 peg 惯量), 旧/缺 XML → ④确定性失败
- **3D 呈现**: tr 通道 peg_yaw/hand_yaw/tt_yaw (0→90→0 旋转可见) + meta.demo_geom {turntable pos/r, coupler pos} → ss_dreamview 按此画转台/压电台
- **夹爪角度通道轴坑 (2026-09-10)**: hand_yaw 必须取手局部 **Z 轴** (col2, yaw0≈世界+X, 随绕z指令线性); 取局部 X 轴 (col0≈世界−Z=旋转轴自身) → XY 投影≈0 → atan2 噪声 ±180° 单帧跳变 (用户"夹爪乱动"实锤, 143 处 169°→−176°, 物理无此运动) — 旋转体朝向角永远别用与旋转轴平行的轴投影

## 验证
- offscreen: `load_flow_file` 后断言节点/连线数 + data×2 + row_bg×4
- 公网: `urllib` POST scene-api.php 3 端点 HTTP 200 + 保存文件可读
- base64 JSON 参数: b64u 可逆 + 页面含 renderJsonDesc

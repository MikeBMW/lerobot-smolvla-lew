# 🧮 状态空间画布工程 + 真实仿真引擎 (2026-08-18 实测)

状态空间模型画布 = **四件套必须全部同步**，缺一就出现"打不开/没逻辑/跑的是占位"：

```
flows/state_space_obs.json          ← 画布 (14 节点: 4 row_bg 背景行 + 10 功能节点)
src/lerobot/policies/left_right/state_space/*.py   ← 六层真实源码 (perception/parallel/dynamics/cognition/safety/execution)
tools/gui/node_logic.py             ← 节点注册 (_reg) + 外部源码映射 (_EXTERNAL_LOC)
tools/gui/state_space_sim.py        ← 仿真引擎 (▶运行 走这里, 不占位)
tools/gui/gen_state_space_video.py  ← 视频渲染 (QPainter 帧 + ffmpeg)
```

## 节点注册/改名全链路清单 (改任何节点名必查)

1. `flows/state_space_obs.json` — name / desc / params.source
2. `node_logic.py` — `_reg(key, [match], doc, fn)` + `_EXTERNAL_LOC[key] = (path, line, sym)`
   - match 关键字用唯一子串 (如 "状态校正器"), 防最长匹配冲突
   - 双击显示真实源码靠 `_EXTERNAL_LOC` (同 left_right 模式), fn 只是占位 log
3. `simulink_module.py` — 详情弹窗 html / 加载日志文案 / 气泡引导 (grep 旧名全清)
4. 左侧模块库 `LIBRARY` 不用手改 — `_load_state_space_library_group()` 从 json 动态加载 (数据一致性: 改画布即同步库, 杜绝手抄漂移)
5. 库按钮支持条目级 type: 渲染处 `lambda t=it.get("type", ntype)` — 状态空间是混合类型组 (model/system/hardware/row_bg)

## 仿真引擎物理自洽铁律 (全部实测踩过)

用户铁律: 不接受拍脑袋参数, 参数必须来自数据或物理推导。以下每条都是仿真"跑不通/假数据"的根因:

1. **状态转移 A 匹配物理**: 默认 A=0.95 每步衰减位置 → 虚假残差 → 频繁否决 → 机器人不动。
   物理自洽 = A=1.0 + B=dt (位置 + 速度指令积分)。AdaptiveStateEstimator.predict 必须乘 B (原实现漏了 B)。
2. **力残差不能被卡尔曼平滑**: 潜状态力维快速跟上实测力 → 接触信号消失 → 调度器永远收不到接触。
   接触力是外部事件不可预测 → 残差力维 = 实测力 (预测恒 0), 不走估计器平滑。
3. **夹爪是开关量, 不参与位置加权融合**: 0.3×1.0=0.3 → 夹爪永远闭不到阈值 → 插入永远不完成。
   融合后 `u[3] = u_ff[3]` 直通; 也不受 saturate 限幅 (限幅只管位置/速度通道)。
4. **插入靠最小推力, 不是比例衰减**: 比例控制近距力→0 + 接触阻尼 → 蜗牛爬行 (稳态 8µm/步)。
   近距 (dist<0.03) 叠加恒定趋近推力 0.03·dir_vec, 阻尼 0.75 下仍能 0.2s 走完最后几 mm。
5. **融合权重按阶段切换**: 接近 = 慢通道主导 (0.3 前馈 + 0.7 校正, 防碰撞);
   抓取/插入 = 前馈推力主导 (0.85 + 0.15 校正兜底)。同一权重全阶段用 → 接近冲太快或插入没力。
6. **状态机推进用 advance(证据) 驱动**: 6 阶段 (接近→抓取→抬起→转移→插入→完成) 由
   接触概率/距离/夹爪/深度证据推进, 别在引擎里手动改 stage_idx。done = stage=="完成"。

## GUI 坑 (2026-08-18 实测)

- **终端字体看不清**: log_box QSS 的 `color:#57606a` 不在 THEMES 映射表 → 暗色主题下暗底深灰字。
  修: log_box 固定 `background:#0d1117; color:#ffffff`, 且 switch_theme 的控件循环里
  `if wdg is self.log_box: continue` (否则主题切换又覆盖回去)。任何自定义颜色都要进 THEMES pairs 或跳过替换。
- **get_external_source sym 匹配 bug**: 匹配逻辑只认 `sym` 或 `sym(` — `class X:` 冒号匹配不上
  → 回退行号定位 → 类重写后行号偏移 → 弹窗只显示几行源码。修: `s.startswith(sym + ":")` 也要匹配。
  影响所有 _EXTERNAL_LOC 节点 (left_right/状态空间)。
- **容器右键「打开源代码」**: 纯 Docker Desktop 容器无 /mnt/c + 无 explorer.exe (WSL interop 断),
  WSL 老链路 (复制到 C:\zmax_src_view + explorer) 必挂。open_node_source 环境自适应:
  `os.path.isdir("/mnt/c") and shutil.which("explorer.exe")` 走老链路, 否则 SourceViewDialog 弹窗
  (绝对路径+行号+📋复制路径+只读源码, node_logic_dialog.py)。

## 视频生成 (QPainter + ffmpeg, 零新依赖)

- PyQt5 QPainter 逐帧画 QImage (offscreen 平台) → ffmpeg 合成 mp4:
  `ffmpeg -y -framerate 25 -i frame_%04d.png -c:v libx264 -pix_fmt yuv420p -crf 20 out.mp4`
- 必须 `QApplication.instance() or QApplication([])` 先创建 (QPainter 无实例会 core dump)
- 引擎 run() 需记录完整轨迹 (x/gripper/force 每步) 供渲染
- 交付: scp 到 ECS `sshpass -p '<pwd>' scp reports/x.mp4 root@39.102.211.79:/www/wwwroot/datadrive.world/` + chmod 644 → 浏览器直接播

## 路径级数坑

`tools/gui/<file>.py` → 仓库根 = `dirname(abspath(__file__))` ×3 (不是 ×2)。
×2 = tools/ → 生成物落到 tools/reports 而非仓库根 reports。
⚠️ 清理目录前先 `git ls-tree -r --name-only HEAD -- <dir>` 查跟踪文件, rm -rf 会误删仓库文件
(本次误删 train_curve_expert_mlp.json, 用 `git checkout HEAD~1 -- <path>` 恢复)。

## 用户追问 (下一会话大概率继续)

- "参数什么时候训练的?" — 现在六层全是手设初值 (Kp=1.2/A=1.0/K=0.5/w_ff=0.3...), 零数据拟合。
  路径1系统辨识: metaworld 或引擎 rollout 数据最小二乘拟合 A/B (x_{t+1}=A·x_t+B·u_t),
  卡尔曼 K=P·Hᵀ·R⁻¹ (R 从数据标定), 调度阈值成功率扫描。路径2: 前馈加速器加载 LeftBrainMLP 真权重。

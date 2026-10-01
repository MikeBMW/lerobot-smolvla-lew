---
name: robot-3dgs-scene-asset
description: "Use when 机器人扫场把环境重建成 3DGS 数字资产(仿真用)。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [3dgs, nerf, gaussian-splatting, sim-asset, robot-camera, handeye, zmax, capture]
    related_skills: [real-handeye-calibration, real-arm-handeye-calibration, sim-real-scene-overlay, cross-venv-model-canvas-node, zmax-scene-engineering, local-vlm-scene-understanding, zmax-state-space-architecture]
---

# 机器人扫场 → 3DGS 数字资产 (仿真测试底图)

## When to Use
- 老倪说「(L5 自主运行/自主学习阶段) 建立当前环境的 3DGS 数字资产, 用于算法仿真测试」「你来同时生场景」「扫描/重建场景」「建数字资产」。
- 要给检测/策略做**仿真回归底图**, 或要仿真-真机同口径对照而缺场景几何。
- 已有采集数据, 要重建/重训/导出资产, 或采集画质/覆盖不够要重扫。

## 核心取舍: 位姿已知 ⇒ 不走 COLMAP/SfM
臂上相机随臂动 = 白送的多视角 + **每个视角都有真值位姿**(50Hz TCP 真值 + 手眼残差 0.06mm)。
所以: **相机外参 = 算出来的, 不是 SfM 解出来的**。省掉整条最脆的链(SfM 失败/漂移/尺度不明), 快且可复现。
只有“相机不在臂上/无手眼”时才退回 COLMAP(这条腿未验证, 别当推荐)。

## 数据源 (本机实测, 只读, 不动在役链路)
| 用途 | 路径/端点 | 实测 |
|---|---|---|
| 臂上 D405 图 | `http://192.168.23.66:8792/frame.jpg` (Orin `rs_fast_node` 压好的 JPEG) | 200 · ~27KB · **640x480** · 可 8~30Hz |
| TCP 真值位姿 | `~/zmax_data/rokae_sdk/tcp_out/latest.json` | 50Hz; 字段 `x y z rx ry rz qx qy qz qw` + `ts`/`t` + `frame:"base_link"` + `joint[12]` |
| 手眼 | `~/zmax_data/handeye_state.json` | `T_cam2tool`(4x4) + `resid_trans_mm_rms`/`resid_rot_deg_rms` + `views` |
| **内参 K + 畸变** | 仓库 `models/real_cam_calib.json` | `K=[394.0623,393.4724,cx 318.4436,cy 238.6584]` · `dist` 5 参数 · `image_size 640x480` · `K_src`=ROS `camera_info`; ⚠️ 它的 `T_base_cam`/`plane_z` 是 **null**(要自己用 `handeye_state.json` 算) |
| 采集器 | 仓库 `tools/gs_capture.py` (--out/--hz/--secs) | 实测 8.19 帧/s · ok=100% · 取图 2.4ms · 位姿配对间隔 2.4ms |
| 落盘 | `~/zmax_data/gs_scan/scan_<时间戳>/` | `frames/*.jpg` + `frames.jsonl` + `session_meta.json` + `capture_summary.json` |

- 另两条慢路: 容器内 raw tap(`ros_arm_tap_raw.py` → /dev/shm, 相机原生 ~1.92Hz, 带 meta) 与 DDS 落盘(`cam_rs.png`)。要实时性就走上面那条高速 JPEG。
- **内参 K 不在采集数据里**: 重建前必须拿到与取流分辨率一致的 D405 内参(Orin 节点 meta / RealSense 出厂标定 / 现场标定)。分辨率与 K 不匹配 = 重建整体错位, 先核这一步。
- 手眼**不要**去 `calib_report_*.json` 拿: 那份的 `解算器.已标定=false`、`手眼=null`(是空报告)。真值在 `handeye_state.json`。

## 流程
1. **先立采集, 再谈重建**。数据错过就没了: 用户说“一会我就动”时, 立刻起采集后台, 再去做环境/训练/接线。
   收工用**会话目录里的 `STOP` 文件**(优雅停, 落 `capture_summary.json`); 别 kill。
2. **采集期间给操作员动作口径**(直接发给他, 别省略): ~30~80mm/s; 加**高度 + 俯仰/侧移**变化, 别只平移一条基线; 相机主要对着工作台/工件区; D405 最近 ~7cm 别贴死; 停在一处不用停久(重复视角无用)。
3. **配对必须用单调时钟**: 墙钟会被 NTP 回拨(本机差 8h)。每帧在**取图前后各读一次位姿** + 记 `fetch_ms`/`pose_t_gap_ms`, 后处理按单调时刻最近邻取; **负帧龄一律拒**。
4. **重建**: 逐帧算 `T_base_cam`, 导出后训练 3DGS。公式/schema/导出格式见 `references/capture-and-pose-math.md`;
   **用 gsplat 自写训练器的骨架/API/归一化/导出与本次真坑见 `references/trainer-with-gsplat.md`**
   (gsplat 的 pip 包只有库、没有 trainer; 交付物优先出 `.splat` + 网页查看器链接, 用户能自己拖转看)。
   - **必须先量相机位姿跨度再决定要不要训**(`np.ptp(pos)`): 只有几十毫米(操作员原地微调观察点) ⇒ 视差不足,
     只能出一张"浅浮雕", **不是环境资产** —— 当场跟用户说清"这只能做小基线验证", 要资产先要一次大范围扫掠。
   - **先去畸变再训**: 3DGS 是针孔假设, 带畸变直接喂会让边缘几何错位 ⇒
     `Knew,_ = cv2.getOptimalNewCameraMatrix(K,dist,(w,h),0)` → `cv2.undistort(img,K,dist,None,Knew)`, **用返回的新 K**。
   - **坐标系口径只选一套并写进产物**: 自用 `cameras.json` 存 **OpenCV 光学系**(x右 y下 z前) 的 `T_cam2world`(base_link);
     对外兼容再写一份 nerfstudio `transforms.json`(OpenGL: y上 z后 ⇒ `T_cam2world @ diag(1,-1,-1,1)`)。
     两套混用/戆错翻转是 3DGS 的经典错位源，产物里写清 convention 字符串。
5. **训练环境隔离**(`tools/gs_env_setup.sh`): 用 `uv`(在 `~/.hermes/bin`) 建**独立** venv。**绝不往 `lerobot-venv` 装东西** —— 它是训练环境且是 uv 管的(里面**没有 pip**)。
   - 需编译 CUDA 扩展的包(nerfstudio/tiny-cuda-nn、diff-gaussian-rasterization、gsplat 的 JIT 版)在本机**装不动: 本机无 nvcc**。走 gsplat **预编译轮**:
     `uv pip install gsplat --index-url https://docs.gsplat.studio/whl/pt27cu128`(配 `torch==2.7.1 torchvision==0.22.1` cu128)。轮子是否命中以脚本末尾自检打印为准。
   - 4060 Laptop **8G 显存**: 同刻只跑一个模型进程; 扫场采集很轻, 但训练与在役推理别叠加。
6. **VLM 指导**(L5 视觉那条): ① 逐帧筛(糊/过曝/遮挡/无效视角)并实时提示换角度; ② 认区域/工装/工件打**语义标签**写进资产元数据; ③ 采集后判覆盖缺口 → 给下一轮**主动视角建议**(位姿级)。
7. **增强件**(按需接, 不阻塞主链): 深度监督(D405 深度图当几何约束, 比纯 RGB 稳) · **4DGS**(每帧 TCP 位姿做时间轴, 可做含臂动态的时间维资产) · **diffusion**(新视角/新光照域随机化; 把机械臂 inpainting 抹掉)。
8. **用途**: 从资产渲染任意视角/光照的“真感”图 → 喂检测/策略做离线回归; 与真机画面做同口径对照(见 `sim-real-scene-overlay`)。
9. **接进画布**: 数据层节点「3DGS 环境资产」, 输入=图像流+位姿流+L5 触发, 输出=资产路径+渲染通道; 跨 venv 子进程桥的写法见 `cross-venv-model-canvas-node`。

## Pitfalls
| 坑 | 症状 | 修法 |
|---|---|---|
| 用墙钟配对位姿与图像 | 全部错位/重建忽明忽暗 | 一律单调时钟; 取图前后各取一次位姿; 负帧龄拒用 |
| 去 `calib_report_*.json` 拿手眼 | 拿到 null 以为没标定 | 手眼真值在 `handeye_state.json`(`T_cam2tool`) |
| 分辨率与 K 不一致 | 重建整体错位/虚 | 取流分辨率与内参分辨率对齐(高速通道是 640x480) |
| 递归查数据根内容 | 命令跑到超时(200s 都不够) | `~/zmax_data` 是几十GB + 上万文件(还有 HF blobs): **只查定点路径** —— `search_files(pattern=…, path=<具体子目录>)` 或 `ls` 逐层下探 |
| 把包装进训练 venv | 训练环境被污染 / 没 pip 装不动 | 另建 `uv venv`; 用 `uv pip install --python <venv>/bin/python` |
| 想装需编译 CUDA 扩展的包 | 报找不到 nvcc | 用预编译轮(index 见上); 或先补 nvcc 再谈源码编译 |
| 把纯 255 过曝面/强反光金属当训练主材 | 3DGS 高斯糊成一片、看不出结构 | 过曝区无梯度: 降曝光/缩光圈, 或纯 255 区掩掉不参与损失; 必要时加深度监督 |
| 采集时把机械臂自身也拍进画面 | 臂被烤进场景, 资材里有幽灵臂 | 相机在臂上时它只对静态场景 ✓; 若其它相机/臂体入镜, 按帧位姿 mask 或 diffusion inpainting 抹掉 |
| 没先拿 K 就开训 | 跑完才发现不可用, 白烧 GPU | 采集第一天就把 K 存进 `session_meta`; 训练前先校分辨率与 K |
| 把上万帧连拍直接喂进训练 | 训练慢/显存吃紧而视角几乎不增 | **先按 6D 位姿最远点贪心抽帧**(平移 + 0.15×朝向差) 到 ~300 张 ——
同视角连拍对重建零贡献。现成工具 `tools/gs_dataset.py`(去畸变 + 选帧 + 出 `cameras.json`/`transforms.json`/`meta.json`) |
| 带着畸变训练 | 画面边缘几何涨开/错位(更像"优化不动") | 先 `cv2.undistort`，用 `getOptimalNewCameraMatrix(alpha=0)` 返回的**新 K** |
| 高速扫场时图像比位姿晚一截 | 运动模糊 + 位姿与像素错配 ⇒ 重影 | 固定延迟(编码+传输)按速度线性放大: ~8mm/s 时 ~20ms≈0.16mm(可忽),
30~80mm/s 时 0.6~1.6mm(占小基线 2~4%) ⇒ 每帧记**位姿龄**并按阈值拒帧, 别拿"取图那一刻"的位姿 |

## 验证口径(交付资产前)
- 资产: ply 高斯数、留出视角 PSNR、资产 bbox 与真实工作区尺度比(与 `env_model.json` 的包络交叉核)。
- 采集: `capture_summary.json` 的 `pose_*_range_mm` 必须非零(**全零 = 臂没动/位姿源不对**), 且帧数与位姿样本数对得上。
- 与真机同口径: 渲染出来的图喂回检测/策略, 与真机同帧做对照(别只报“看着像”)。

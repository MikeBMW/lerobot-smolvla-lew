# MLP 前馈探针 + 可视化节点 (2026-09-04, 老倪: "我想看到前馈加速器在想什么")

## 能力归因 (先讲清, 老倪追问过)
- 插拔能力 ≠ 某一层 (W1/W2 各 262K 参数) — 是 39D→512→512→512→4 整个复合函数 +
  26942 帧教师标签共同编码。分工近似: W0=编码(观测→特征), W1/W2=特征组合, W3=解码(→动作)。
- 蒸馏真相: 模型=解析教师轨迹的蒸馏 (export_dataset 标签=解析律输出), 所以 align_ff_kp
  拟合 Kp≈1.2 完美是"蒸馏保真"而非巧合。

## 探针实现 (parallel.py mlp_ff_forward, probe=None 零开销)
- FeedforwardAccelerator.__init__ 建 self.probe={} 传 mlp_ff_forward(npz, probe); 每 forward tick 更新:
  - obs 语义: hand[0:3]/target[36:39]/d_h(3D)/d_xy/gripper
  - layers[3]: 每层 active 数/能量(L2)/top3 活跃单元 (ReLU 后 40-55% 稀疏是常态)
  - out_contrib: u 每维归因 = argmax_j |W3[d,j]·x3[j]| (谁在指挥该输出维)
  - act_raw: [x1,x2,x3] 全量 512 激活 (画直方图/散点用, 3×512×4B/帧 开销可忽略)
- GUI 节点链: node_ss_s2 (⚡节点) 把 accel.probe 存 `_SS_STATE["ff_probe"]` → 下游可视化节点读

## 两个可视化节点 (tools/gui/, QDialog+QPainter 自绘, scope 深色风格)
- 🧠 前馈激活直方图 (node key ss_ff_hist, ff_hist_view.py): 三层各行直方图,
  FIFO 150 帧激活池 × 64 bins; x=0 虚线=ReLU 截断 (0 处高峰=休眠神经元=稀疏激活,
  右尾=正在工作的特征); 白灰=累积分布 + 朱红=最近一帧叠加; 每行右侧 u_ff, 顶 obs 摘要。
  QTimer 100ms 节流重绘 (≤10Hz 防每 tick 全量重绘卡 GUI)。
- 🎯 归因·分工 (node key ss_ff_attrib, ff_attrib_view.py): 上半=归因堆叠图
  (每帧 4 输出维驱动能量 contrib_d=Σ|W3[d,j]·x3[j]| 堆叠柱, 看阶段切换谁主导;
  通道色=朱红 dx/黑 dy/中灰 dz/浅灰 gripper); 下半=512 单元功能散点:
  每单元=时间激活 profile (150帧, 每帧中心化去全局同步) → PCA(SVD 即时) 或 t-SNE;
  颜色=静态分工 argmax|W3[:,j]| → 同色成簇=功能分群。
- 窗口单实例全局变量 (_FF_HIST_WIN/_FF_ATTR_WIN), 节点执行时 push+show+raise_,
  PyQt5 延迟 import (无 Qt 的 CLI 环境不炸)。

## 纯 numpy t-SNE (gui-venv311 无 sklearn, 实测 ~2s/512点/400iter)
- 输入 X (N=512 单元, D=帧); 每点二分求 sigma 满足 perplexity (40 iter);
- 梯度向量化: A=(P−Q)/(1+Dq); grad = 4·(Y·A.sum(1,keepdims) − A@Y) — 别用三重广播
  (曾写出 (N,N,N) 数组 + broadcast 错误); 动量 0.8; 每 iter Y−=mean。
- 坑: 单元样本矩阵方向 (512×帧), 转置传帧×512 会让 N=帧数 → IndexError 画图越界。

## 无头验证模式
- QT_QPA_PLATFORM=offscreen + gui-venv311 (PyQt5+pyqtgraph); parallel.py 用
  importlib.spec_from_file_location 文件加载 (绕开 lerobot 包 __init__ 的 huggingface_hub 依赖)。
- 验证: win.push 60-100 帧真实激活 → grab().save(png) 检查尺寸/非黑像素 (直方图内容占比
  低是正常的 — ReLU 稀疏把大量 0 堆在 x=0 一个 bin)。
- QPainter drawText/fillRect 坐标必须 int() (PyQt5 严格类型, float → TypeError)。

## GUI 新节点接入三处 (漏一处在画布永远看不到 — 老倪当场抓)
① tools/gui/node_logic.py: 执行函数 + `_reg(key, matches, doc, fn)` (matches 决定名称搜索)
② flows/state_space_obs.json: nodes[] 加节点 {id,type:'model',name,x,y,w,color,icon,
   params:{state_space:true, desc, source}} + links[] 连线 {id,f,t,f_port,t_port,label}
   (f/t=节点 id 如 'ssff'; 连线 label 如 '激活探针') — 状态空间画布/LIBRARY 都由该 json 生成
③ LIBRARY 组自动 (_load_state_space_library_group 读 json), 不用手改
- 放置: 从 ⚡前馈加速器(ssff, x=1140,y=80) 正下方引 (同列) 视觉自然; 先跑碰撞检测
  (排除 type=row_bg 背景条)。
- node_logic.py 改动必须重启 studio.py 才生效 (进程内旧代码), 老倪问"怎么没有"先查重启。

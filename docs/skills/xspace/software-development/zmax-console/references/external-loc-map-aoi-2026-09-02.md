# 画布节点源码映射校验 + AOI 质量检测真实化 (2026-09-02)

## 一、_EXTERNAL_LOC 三要素校验 — 用户连续追问"节点源代码是 [别的代码]"的根因

### 症状
用户连续三轮问:
- "为什么前馈加速器和自适应状态估计器源代码都是 [同一段 forward]?"
- "外观质量检测的代码为什么放到 node_logic.py?不是应该放到 src/lerobot/policies/yolo_3d 吗?"
- "自适应状态估计器的源代码,应该是 class AdaptiveStateEstimator 这个类里,你还没改好"

### 根因(三类)
1. **行号错位**(最常见): 双击编辑器显示对的类(get_external_source 用符号名匹配截取, OK),
   但 VSCode 打开定位到错行号 → 看到别的代码。典型: `_EXTERNAL_LOC["ss_est"]` 行号 34
   实为 45(类定义行), VSCode 打开 parallel.py:34 正好是 FeedforwardAccelerator.forward 的
   代码 → 用户以为"自适应状态估计器源码=forward"。
2. **符号名不存在**: yolo_tactile 写 "gen_tactile" 实际是 `def synth_tactile`; ss_bg5 的 sym
   误写路径字符串 "planner.py"(根本不是符号)。
3. **粒度不对**: ss_sched(动作调制器)映射整个 class ActionModulator(164 行), 用户要的是
   decide 方法本体 → 映射应给 `def decide`。

### 全量校验脚本(2026-09-02 一次查出 29 条映射 12 处错位, 全修)
```python
import sys, os
sys.path.insert(0, 'tools/gui')
import node_logic
loc = node_logic._EXTERNAL_LOC
bad = 0
for key in sorted(loc):
    path, line, sym = loc[key]
    lines = open(path, encoding='utf-8').read().splitlines()
    real = None
    for i, ln in enumerate(lines, 1):
        s = ln.strip()
        if s == sym or s.startswith(sym + '(') or s.startswith(sym + ':'):
            real = i; break
    if real is None:
        print(f'{key}: ❌ 符号找不到 {sym} ({os.path.basename(path)})'); bad += 1
    elif real != line:
        print(f'{key}: ❌ {line}→{real} ({sym})'); bad += 1
print(f'--- 共 {len(loc)} 条, 错位 {bad} 条 ---')
```
校验后的 `get_external_source(key)` 首行应为期望符号; `get_node_location(key)` 行号应为
真实定义行。改完必须重启 studio.py。

### 铁律
- 新增/修改 _EXTERNAL_LOC 三要素(绝对路径, 行号, 真实符号名)必须跑上述校验。
- 符号名匹配是源码截取的关键(截取到下一个顶层 class/def/@ 为止), 行号只是 VSCode 兜底。
- 用户说"XX 节点源码应该是 YYY" = 要么行号错位、要么符号错、要么粒度不对, 先跑校验再改。

## 二、AOI 外观质量检测真实化 — quality_check.py 三件套

### 背景
用户: "新建 quality_check.py 放 yolo_3d 下, 架构不变" — 外观质量检测节点(ss_aoi)原来
只加载 detection_targets.json 清单(无实际检测), 且缺 _EXTERNAL_LOC 映射。

### 落地
1. **真实实现**: `src/lerobot/policies/yolo_3d/quality_check.py`
   - `AOIQualityChecker.check(frame)` 真实图像处理缺陷检测, 对照 flows/detection_targets.json
     的 DET-AOI-01~04 四目标:
     - 清晰度 = 拉普拉斯方差 (cv2.Laplacian(gray, CV_64F).var())
     - 划痕 = Canny + 概率霍夫直线 (长直线条数)
     - 污染 = 高斯模糊差分 + connectedComponentsWithStats 斑点
     - 氧化/镀层缺损 = 灰度中值偏移
     - 毛刺/变形 = 边缘像素占比
     - DET-AOI-03 显微复检: 非显微帧标注跳过(not-applicable), 不误判
   - 阈值可配 (_DEF_TH + thresholds 覆盖), 产线标定起点
2. **节点胶水**: node_ss_aoi 改 importlib 加载 quality_check → 取 YOLO 缓存帧(_YOLO_CACHE["img"],
   无则 _yolo_capture 同源采样) → check → 缓存 _YOLO_CACHE["aoi"] → 日志逐项数字+判据+pass/fail
3. **映射**: `_EXTERNAL_LOC["ss_aoi"] = (yolo_3d/quality_check.py, 40, "class AOIQualityChecker")`

### 坑
- **HoughLinesP 返回形状 OpenCV 版本差异**: 旧版 (N,1,4), 新版 (N,4) →
  `segs = lines[:, 0] if lines.ndim == 3 else lines`(否则 IndexError: too many indices)
- **真实执行原则(老倪工程真实性)**: 仿真全景帧(480x480 metaworld corner2)含机械臂/孔结构
  边缘, 按产线金手指阈值测必然 FAIL(实测划痕 61 条 vs 判据 ≤6)— 这是物理事实, **诚实
  呈现 FAIL + 日志标注"场景级基线; 金手指/端面 ROI 特写检测需真机显微帧"**, 不许写死 pass。
  真机接 YOLO 框裁剪 ROI 后再跑就是真实缺陷判据。

## 三、node_ss_s2 估计分支只 predict 没 update(画布"自适应状态估计器"名不副实)

node_logic.py `node_ss_s2` 的"估计"分支原来只调 `est.predict(...)` 就存回 latent —
卡尔曼校正(update, 用观测 z_k 修正先验)根本没执行。修复: 补 predict→update 闭环:
```python
z_k = np.concatenate([obs39[0:3], [obs39[3]]])   # 观测: 手位置 + 夹爪开度 (与 latent 同维)
latent = est.update(np.asarray(latent_pred, dtype=float), np.asarray(z_k, dtype=float))
_SS_STATE["latent"] = np.asarray(latent, dtype=float)
```
验证: predict 先验 [0.095 0.19 0.285 0.475] → update 校正后 [0.1075 0.2 0.2975 0.4375],
与手算一致。教训: 画布节点标注"预测-校正"就必须真的执行两步, 只做一半 = 模拟伪装。

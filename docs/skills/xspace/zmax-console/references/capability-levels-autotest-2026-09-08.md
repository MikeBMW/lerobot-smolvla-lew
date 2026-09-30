# 三级能力 L2/L3/L4 自动测试 + 源码映射漂移修复 (2026-09-08 v5.2 会话)

老倪命题: 做功能清单(基础/高级/专家三级) + 测试用例 + 自动测试, 参考自动驾驶分级:
- **L2 基础辅助** = 车道保持+ACC (人在环分段技能) → 分段式小模型技术 (YOLO/前馈MLP/状态机/原子技能)
- **L3 高级 NOA** = 高速 NOA (特定场景自主) → 端到端模仿学习技术 (VLM + Flow-Matching ActionHead)
- **L4 专家城区** = 城区 NOA+自主恢复 → 世界模型技术 (潜空间预测+流形导航+肌肉记忆)

三级语义定稿 (老倪原话): 专家功能=世界模型技术 / 高级功能=端到端模仿学习 / 基础功能=分段式小模型。

## 交付物
- `src/lerobot/verification/capability_levels.py` — CAPABILITY_LEVELS 注册表 (L2 9功能/L3 3功能/L4 7功能,
  summary+funcs+groups); resolve_tests(level) 把每级功能的方法组前缀 (yolo/2d3d/tac/ff/sched/lim/skill/
  act/world/sobs/rsn/llm/est/pred/mc/mp/lat/cal/inn...) 展开成 verification_layer 真实断言方法名。
- `tools/ss_level_tests.py` — CLI: `--list` / `--level L2` / 全量; run_level 逐个 getattr + fn(np) 调用
  (VerificationLayer 断言签名是 fn(np), 不是 fn(None)!), 输出 ✅/❌ + detail。
- `docs/capability_levels_L2L3L4.md` — 升级路径 (L2→L3: VLM权重+ActionHead训练+端到端模式;
  L3→L4: 世界模型实时接入+流形导航闭环+多布局恢复)。

## 实测结果
L2 161/161 ✅ · L3 54/54 ✅ · L4 82/82 ✅ = 297 真实断言全绿。

## 血泪坑 (都踩过)

1. **断言方法必须 fn(np) 不是 fn(None)**: VerificationLayer 的 t_* 方法签名 `(self, np)` — np 是 numpy
   模块 (同 run_tree 内部 `r = fn(np)`)。传 None → 一半方法崩。执行器照抄 run_tree 调用模式。

2. **resolve_tests 前缀正则必须 `t_{g}($|_)`**: 否则前缀 yolo 会误匹配 t_yolo_xxx 之外的 t_yoloabc;
   方法名前缀分类 (grep -oE 'def t_[a-z0-9_]+' 后 sed 归一) 是快速盘点手段。

3. **import 路径**: capability_levels.py 在 src/lerobot/verification/ 下, ROOT 需 4 层 dirname 到仓库根
   (文件在 <repo>/src/lerobot/verification/); resolve_tests 用 importlib spec_from_file_location 直接
   载 verification_layer (sys.path 加 src 不一定够, 因为 verification 包内 import 依赖)。

4. **源码映射行号漂移 = t_auto_srcmap 自动揪出 (本会话 7 处)**: t_auto_srcmap 读 node_logic._EXTERNAL_LOC
   的 (path, line, sym), 查 `lines[line-3:line+2]` 附近是否含 sym — **只查手写行号±3, 不做动态符号搜索**。
   源码重写后行号漂移 → 双击/右键跳到错代码 (老倪红线: "源码不是这个")。2026-09-08 修复清单:
   - yolo_align: 62→65 (yolo_state_aligner.py def detect_3d)
   - ss_bg2/ss_ff: 100→117 (parallel.py class FeedforwardAccelerator)
   - ss_est: 158→186 (class AdaptiveStateEstimator)
   - ss_pred: 14→62 (dynamics.py class PriorDynamicsPredictor)
   - ss_sched: 167→179 (cognition.py def decide)
   - ssvlm: 1→312 (modeling_smolvla_lew.py class SmolVLALewPolicy)
   - ssdec: 原指 manifold_layer 138 "潜空间解码" (无此符号!) → 改指 smolvla_lew/action_head.py 205
     class SmolVLALewActionHead
   **铁律**: 新增 _EXTERNAL_LOC 必须指真实存在的符号且行号=实际行 (grep -n 先查); 每轮跑
   `gui-venv311/bin/python tools/ss_level_tests.py --level L3` 验证 srcmap; srcmap 只报前一批 bad,
   修完重跑会暴露下一批 (逐批收敛)。

5. **flow JSON w/h/x/y 必须 int — str 会让画布 Fatal Abort (本会话 GUI 崩根因)**: 脚本往
   flows/state_space_obs.json 追加节点时若 w/h 写成字符串 ("110") → SimNodeItem.boundingRect
   `QRectF(0, 0, self.w, self.h)` TypeError (arg 4 unexpected type 'str') → **Fatal Python error:
   Aborted 整个 GUI 崩** (日志只留 TypeError + Fatal, 无栈到用户界面)。修复: 一次性遍历 nodes 把
   w/h/x/y 全部 int(float(v))。**铁律: 程序化改 flow JSON 后必须 python 校验所有节点 w/h/x/y 是 int,
   再重启 GUI; 崩溃先看 studio_launch.log 的 TypeError/Fatal 行**。

6. **AOI 真实图 glob 只认 jpg**: t_auto_aoi_realimg 原只 glob *.jpg, data/yolo_peg_depth/images/ 存的是
   *.png → "无真实图像样本" FAIL。glob 补 png 路径 (outputs/yolo_peg_depth 或 data/yolo_peg_depth/images)。

7. **旧 GUI 进程杀不净 = 双实例叠窗**: restart 脚本 pgrep+kill 后旧实例可能残留 (kill 非 -9 / 时序),
   两个 studio.py 叠同一 X 显示, 用户看到旧代码行为。杀进程用 kill -9 + `ps aux | grep '[s]tudio.py'`
   确认归零; 新实例窗口标题版本号是唯一可信证据。

## 与既有体系关系
- 规范场三层树 (node_func_tree.py, G1/G2/G3 22节点/111功能/553用例) = 技术视角;
  PRODUCT_TREE (L1/L2/L3 产品作业) = 客户作业视角; **capability_levels L2/L3/L4 = 自动驾驶分级视角**
  (老倪 09-08 新口径, 对应画布三级能力行: 🚀高级=端到端/VLM+FlowMatching · 🏆专家=世界模型/流形 ·
  🔧基础=分段式小模型)。三个清单并存不冲突。
- 新画布高级层节点 (VLM/Decoder) 注册 node_logic 时同步挂 _EXTERNAL_LOC (见坑 4), 否则 srcmap FAIL。

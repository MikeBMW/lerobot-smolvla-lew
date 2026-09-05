# 全仓业务术语统一: 插销/peg → 光模块 (2026-09-04, 老倪指令, 102 文件 470+/462-)

Z-MAX = 光模块工厂自动化; metaworld 仿真遗留"插销/peg"术语与产品口径不符。老倪要求
"所有代码/注释/表述 + YOLO 检测结果"都换成光模块。分层执行策略 (直接机械全替换会砸环境):

## 可安全全换 (表述层)
- 中文"插销" 256 处 → 光模块 (注释/日志/GUI 文案/文档全文本替换; py/md/yaml/json/txt/html)
- 注释/docstring/日志里裸词 `\bpeg\b(?!-)` → 光模块 (排除 pegGrasp/peg_z0/peg-insert 复合:
  正则后视 (?!-) 挡 peg-insert; 下划线/点自然不匹配 \bpeg\b)
- 单字"销"白名单词组: 销头→光模块头/触销→触光模块/持销/握着销/销料位/销上方/销未对孔/
  销到孔沿 — **勿碰**: 治具真实零件"定位销/对接销/工装定位销"(flows/gen_scenes*.py 是
  工厂夹具, 不是光模块!); "开销"的销是误报
- GUI 日志 f"光模块={obs[4:7]}" 等 (用户可见全换)
- 脚本: 逐行状态机 (docstring 三引号区间/行内 # 后), 代码区不碰; md 只换中文插销
  (英文 peg 全是技术专名: peg-insert/nut-on-peg/数据集名); 跑完 py_compile 全量 + grep 残留复核

## 保留层 (动了会砸, 注释说明即可)
- metaworld mujoco site 名 pegGrasp/pegHead (env.model.site() 绑定), 任务名 peg-insert-side-v3
- 代码变量/标识符: peg/PEG_POS0/d_hp/self.peg (数据流一致性; 注释已写"光模块")
- 数据集/权重目录/文件名: data/yolo_peg/train_peg_rl.py/peg_depth_v1 等产物引用
- 引号 dict 键 (d["peg"]), gen_yolo_data.py 类 id 映射 {hand:0,peg:1,hole:2} — **id 顺序
  与已训权重绑定, 训练标签生成侧勿改**

## YOLO 检测结果业务化 (老倪补充要求) — 关键坑
- **覆写底层 names 才生效**: `self.model.model.names[cid]='光模块'` — 顶层 `self.model.names`
  赋值不生效 (实测打印仍是 peg); 覆写后 predict 的 res.names/cls、det3d 键、GUI 画框
  (_vis["boxes"] 读 res.names) 全自动变业务名
- 同步改 det3d 键消费链: yolo_state_aligner z_map 键 + align() 的 if "peg" in det3d /
  det3d["peg"] → "光模块"; state_space_sim_real.py / diag_depth_align.py 消费点;
  循环消费 det3d[k] 的 (simulink 8786/probe_r1_calib) 自动跟随不用改
- 深度模型权重 names={0:'depth'} 单类, 别拿它验证 (glob 排序会先取到它)

## 验证
- git ls-files 排除 data/outputs/models 统计残留; "插销" 应 0 (tracked);
  剩余 peg 全在保留层 (site/变量/数据集名/引号键)
- 全量 py_compile (含 gui-venv311 的 GUI 文件, lerobot-venv 无 ultralytics/PyQt5 装不上)

# 2026-08-08 总系统标准化 + Z-MAX 架构迁入模块库 + 三模型对比删除

老倪指令流: "控制台删除三模型对比的按钮和功能; 5模型对比改成模型对比" →
"总系统这几个node也要标准化; 也要在左侧模块库显示" → "system2/sys12/sys11/sys0 都迁移到simulink的模块库; 保留返回首页功能"

## 三模型对比删除 (全引用清单 — 漏一处就坏引用)

删除"🔬 三模型对比"必须清 4 类引用 (grep "三模型对比" 全文件核对):
1. **模板定义** (LIBRARY 区两个模板: "🎛 总系统·三模型对比" + "🔬 三模型对比" — sed -i '行号范围d' 删, 先 cp 备份)
2. **LIBRARY 模板按钮条目** (模板列表 dict, {"name": "🔬 三模型对比", ...})
3. **侧边栏按钮** (btn_compare3 + tl.addWidget)
4. **open 方法** (open_compare3 — 整方法 patch 删)
5. **残留文本** (open_topsys 内 load_reference_app_by_name("🎛 总系统·三模型对比") → 改新模板名; _topsys_hint 气泡文本)

"五模型对比" → "🔬 模型对比": sed 全替换 + 保留 btn_compare5 (七模型纵向对比), 删 btn_compare (其 open_compare 加载已删模板 = 坏引用).

## 总系统标准化 (Subsystem 节点)

- 模板 "🎛 顶层总系统": 3 节点 [📦metaworld_peg 数据 → 🔬 总系统(Subsystem) → 📊对比评估Scope], subsystem 指向 **"🔬 模型对比"** (不是三模型!)
- LIBRARY 按钮条目 {"name": "🎛 顶层总系统", "template": "🎛 顶层总系统"}
- **node_logic.py 注册** (_reg("topsys", ["总系统","Subsystem"], ...) — 双击展开 subsystem 模板; 记忆铁律"新节点须注册node_logic")
- open_topsys 加载名必须 = 模板名 (🎛 顶层总系统)

## Z-MAX 架构模板 (老倪架构布局: 三行横排非三列)

("🏗 Z-MAX 架构", 4 节点) + LIBRARY 按钮条目:
```
🖥 SYS2 云端训练        ← 顶行
    🧠 SYS12 Z-Flow   🖐 SYS11 VLA-T   ← 中行 (SYS1 层并列)
        🔧 SYS0 硬件驱动                 ← 底行
```
links (0,1),(0,2),(1,3),(2,3); 布局三行横排 [[SYS2,"","",""],["",SYS12,SYS11,""],["","",SYS0,""]]

## 模块库可拖节点组 (老倪第二次纠正: "主页左侧模块库还是没迁移")

模板按钮 ≠ 模块库节点! 老倪要的是**左侧 LIBRARY 分组里可拖条目** (像数据源/模型/Scope 一样点击拖入画布):
- LIBRARY 加分组: ("system", "🏗 Z-MAX 架构 (4)", [{name:"🖥 SYS2 云端训练", params:{desc}}, ...4 条目]) — 挂在 "系统 (8)" 组后
- 拖入画布: 条目走 add_node_at_center("system", name, params) (注意不是 add_node — 签名无 node_type)
- 主页 SystemLayerCard (sys2/sys12/sys11/sys0) 是 studio.py 的卡片 — 模块库版本是 simulink_module 的 LIBRARY 组, 两者并存

## 首页三层系统 (studio.py 侧边栏 — 老倪"模块库改成三层系统")

老倪: "首页的模块库，改成三层系统" + "那几个字改成 三层系统"。**主页左侧 SystemLayerCard 4 卡 → 3 卡**:

```
🖥 System 2 · L4级大脑 · 云端训练    ← 顶 (SYS2_COLOR)
🧠 System 1 · VLA-T + Z-Flow        ← 中 (SYS11_COLOR, 合并原 sys11/sys12 两卡)
🔧 System 0 · L2基石 · EtherCAT     ← 底 (SYS0_COLOR, 红底)
```

- SystemLayerCard("sys1", "System 1", "VLA-T + Z-Flow · 500M/15M", SYS11_COLOR, "SYS11 VLA-T 动作 · SmolVLA 500M\nSYS12 Z-Flow 引导 · LeWorldModel 15M")
- **删卡后必须 grep `self\.sys11|self\.sys12`** — 残留属性引用 → AttributeError (本轮无残留, 但改卡先查)
- layer_map 加 `"sys1": "training"` (SYS1 卡跳训练页; sys11/sys12 映射保留供其他入口)
- 标签 `sep_label = QLabel("三层系统")` (原"模块库")
- 验证: 侧边栏类构造 (next obj hasattr layer_clicked) + hasattr(side,"sys1") + not hasattr(side,"sys12")

## 功能模块顺序重排 (studio.py HomeWidget._modules_grid)

老倪指定顺序 (11 模块, 4×3 网格 i//3, i%3):
```
第一行: 数据集管理 dataset · 训练控制台 training · 硬件工具箱 hardware
第二行: 系统架构 architecture · Simulink模式 simulink · 配置中心 config
第三行: 全局数据空间 dataspace · 实时监控 monitor · 评估分析 evaluation
第四行: 插拔场景 plugging · 版本同步 version
```
- 直接重排 `modules = [...]` 数组顺序即可 (每元组 (mid, icon, title, syslbl, desc, color) 不动)
- 验证: `re.findall(r'\("(\w+)",', seg)` 提取 mid 序列 == 期望顺序; 运行时 `container.layout()` (返回是 QWidget container 包 QGridLayout — 不是 layout 本身!) 数卡数 == 11

## 功能模块分组标题 (老倪: "每层增加一个层级标题, 让用户能区分每层都是一类")

4 层标题: **系统/架构/数据/场景** (第一行=系统, 第二行=架构, 第三行=数据, 第四行=场景)。实现 (HomeWidget._modules_grid):

```python
_GROUP_TITLES = ["系统", "架构", "数据", "场景"]
for i, (mid, ...) in enumerate(modules):
    row_cards = i // 3
    if i % 3 == 0:  # 每行第一个卡前插标题 (跨 3 列)
        tlab = QLabel(_GROUP_TITLES[row_cards])  # SYS2_COLOR 粗体
        grid.addWidget(tlab, row_cards * 2, 0, 1, 3)   # 标题行 = 偶数行
    grid.addWidget(card, row_cards * 2 + 1, i % 3)     # 卡行 = 奇数行
```

- **关键**: grid 行号 ×2 — 标题行占一行 (偶数行 0/2/4/6), 卡在下一行 (奇数行 1/3/5/7)
- 验证: itemAtPosition(偶数行, 0).widget() 是 QLabel 且文本 == ["系统","架构","数据","场景"]; 奇数行各 3 卡

## 产品主页卡 (打开官网 URL 的功能卡)

老倪: "增加一个功能卡叫 产品主页, 连接到 https://datadrive.world/, 放到最后一个"。

1. modules 数组末尾加: ("website", "🌍", "产品主页", "datadrive.world", "产品官网 · 技术展示\nhttps://datadrive.world", "#1f6feb")
2. **StudioMainWindow._on_nav 加特殊分支** (像 check_updates 一样提前 return — modules dict 无 website 页, 不查页):

```python
if target == "website":
    from PyQt5.QtCore import QUrl
    from PyQt5.QtGui import QDesktopServices
    QDesktopServices.openUrl(QUrl("https://datadrive.world/"))
    return
```

- 验证: 12 卡入网格 + mid 序列最后 == "website" + openUrl 代码存在

## 注意

- "返回首页"按钮在 **studio.py** (QPushButton "← 返回首页" + sidebar 项) — 不在 simulink_module; 验证断言查 studio.py
- 删模板后 open_* 方法若加载旧名 → load_reference_app_by_name 返回 False 静默失败 → 必须 grep 清名
- 验证: 三文件语法 (simulink_module/node_logic/studio) + 模板实际加载 (load_reference_app_by_name 返回 True + 节点数 ≥ 期望)

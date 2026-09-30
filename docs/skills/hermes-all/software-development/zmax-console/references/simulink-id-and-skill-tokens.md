# Simulink 页(simulink_module.py)— ID 一致性 / z 层级 / 原子技能 Token 链路

适用:`tools/gui/simulink_module.py`(独立窗口,非 studio.py 内)。所有坑均 2026-08-09 实测踩过并修复。

## 1. VEH.5 ID 体系 — 模块库与画布必须数据一致

- `LIBRARY_SEQ` = {模块名 → 稳定序号},模块加载时从 LIBRARY 构建(遍历顺序 1..N)。
- 画布节点 nid 显示 = `lib_seq_of(node.name)`,**与左侧模块库按钮同一序号**(SYS2 云端训练 = VEH.5.065 两边一致)。
- 模块库按钮 tooltip 也显示 `VEH.5.{lib_seq} — 名称 (与画布节点 ID 一致)`。

### 撞号事故(VEH.5.22 / VEH.5.25 反复出现)
1. **模板节点名不在 LIBRARY** → `lib_seq_of` 返回 None → 回退 `id % 100`(gen_id 是 `n<ts><rand>`,取模随机且会撞号,如 `...525 % 100 = 25`)。修:`REFERENCE_APPS` 模板所有节点名注册进 LIBRARY_SEQ(续号)。
2. **`_veh5_apply`(控件通用编号器)覆盖模块库按钮 tooltip** → 用户 hover 模块库看到 VEH.5.22/32(通用布局序),画布却是 065 → 不一致。修:`_veh5_apply` 跳过模块库按钮(`_lib_btn_ids`)。
3. **画布节点 ID 只在 hover 时画** → 用户"看不到/常显"困惑。修:paint 里 nid 常显(不依赖 `_hover`)。
4. CICD 环节节点 sid 是字符串,"① 采集" 等,`% 100` 会 TypeError(被 try 吞 → 无 ID)。修:CICD 环节名也注册进 LIBRARY_SEQ。

### 判定顺序(遇到"ID 不对/撞号/不一致")
1. `lib_seq_of(节点名)` 是否 None → 模板名未注册
2. `_veh5_apply` 是否覆盖了模块库按钮 tooltip
3. 用户窗口是否旧代码(进程启动时间 vs git log — 重启控制台再看)
4. offscreen 实例化打印全部节点 nid + LIBRARY_SEQ keys 对比,先数据后视觉

### ⚠️ 删除按钮后序号重排陷阱(2026-08-09 反复踩,连环删错)
- 用户"删除 VEH.5.13"→ 删除该 LIBRARY 项后 **LIBRARY_SEQ 整体重排**,原 14 号变成 13 号 → 用户窗口(未刷新)看到 13 号位还是有个按钮 → 说"没删掉"。
- **致命错误模式**:我每次删"当前 13 号",删完重排又有个新按钮顶到 13 号 → 用户再说删 13 → 连环误删(M01 ACT → VLA-T → GR00T 全被删过又恢复)。用户窗口显示的可能一直是**同一个按钮**(他们记住的是按钮外观,不是序号)。
- **正确做法**:①删除时先 offscreen 确认当前 seq 对应哪个按钮并明确告知用户("当前 13 号 = X,将删除");②删完立即说明"序号已重排,13 号位现在是 Y,你看的按钮(X)已删";③不要循环删"当前 13 号";④用户说"VLA-Touch 没删掉"这类反馈 = 用户要删的是**那个名字的按钮**,直接按名字删,别纠结序号。
- 通用:删 LIBRARY 项用精确 name 锚点 `{"name": "M02 VLA-T",` 整行删;恢复误删用 `git checkout --` 回到 HEAD 再单步重做。

### ⚠️⚠️ 两套 VEH.5 编号体系(2026-08-09 终极教训 — 连环删错 4 次的根因)
Simulink 窗口里 **VEH.5.xx 有两套独立编号**,用户说"VEH.5.13"必须先确认指哪套:
1. **LIBRARY_SEQ 序**(模块库按钮 tooltip,遍历 LIBRARY 1..N)——我一直在删这套的按钮。
2. **`_veh5_apply` 控件布局序**(工具栏 mk_btn 按钮/画布控件,VEH.5.01-187,按 y 坐标排序)——**工具栏按钮只有这套编号**!
- 用户要删的 VEH.5.13 实际是**工具栏"🖐 VLA-Touch"按钮**(btn_vlatouch):工具栏布局序 ▶运行(1)→⏭单步(2)→⏹停止(3)→🧭引导(4)→⛶浮动(5)→💾另存(6)→📂加载(7)→💾保存模型(8)→🔴录制(9)→⏹停止(10)→🎯数据闭环(11)→🔬Model Zoo(12)→**🖐VLA-Touch(13)**→🧿AWE(14)→🎛总系统(15)→⬅返回(16)。
- 我按 LIBRARY_SEQ 删了 M01 ACT、VLA-T、GR00T 三个模块库按钮(用户没让删)→ 用户说"你删错了,恢复"。
- **正确流程**:用户报"VEH.5.xx 按钮"→ ①offscreen 实例化 SimulinkModule,分别列出 LIBRARY_SEQ[xx] 和工具栏按钮布局序[xx](按 y 排序取第 xx 个)→ ②若工具栏按钮匹配用户描述(如"工具栏上面"、能加载模板)→ 删工具栏按钮;③删前先告知用户删的是哪个名字的按钮。
- **删工具栏按钮三处清理**:赋值行 `self.btn_xxx = mk_btn(...)` + `tl.addWidget(self.btn_xxx)` 都要删(先 `grep -n btn_xxx` 查全部引用,别只删赋值行 → IndentationError);若按钮名/方法(如 open_vlatouch)被别处引用要一并查。
- **工具栏加按钮**:`self.btn_atomic = mk_btn("🧩 原子", "tip", self.open_atomic_skill_flow, "#00d4aa")` + `tl.addWidget(self.btn_atomic)`,插在目标位置(如 btn_awe 前)。
- **误删模块库项恢复**:`git show <上一commit>:tools/gui/simulink_module.py` 取出被删项文本(以 `{"name":` 为起点、`},` 为终点),重新插入到原位置(如 `🧿 AWE 完整模型` 前)。比 `git checkout --` 整个回退更精准(保留本会话其他已提交改动)。

### ⚠️ 用户"没看到 X 按钮"四连报的终极处理(2026-08-09 原子按钮案例)
- 用户反复"VEH.5.13 没删 / 原子没加上",即使 offscreen 已验证代码 100% 正确(LIBRARY 里有、tooltip 对)。
- 原因链:①用户窗口旧代码(进程 vs git log 时间对比)②删除重排导致 13 号位总有按钮 ③**新按钮位置不够显眼**(原子在模型组第 1 个,但模型组在 LIBRARY 中段,用户没滚到)。
- **终极解法**:把用户要的按钮做成**模块库最顶部独立分组**(`LIBRARY = [` 后第一个元素,如 `("skill", "🧩 原子技能入口", [{"name": "🧩 原子", ...}])`),用户打开模块库第一眼看到,不再依赖滚动/分组位置。验证:`names[0] == "🧩 原子"` + `LIBRARY_SEQ` 第一个 = 1。
- 教训:用户反复报"没看到"时,除了刷新/重排解释,主动**提升可见性**(最顶/置顶/高亮),别只重复"代码是对的"。

## 2. QGraphicsScene z 层级 — row_bg 背景盖住节点(颜色模糊)

- 现象:加载 model_zoo.json 后节点颜色模糊。
- 根因:SimNodeItem 构造函数 `setZValue(10)` 对所有类型生效;row_bg(背景行)在 JSON 末尾 → 后 add → 同 z=10 渲染在正常节点**上面** → 半透明色带遮挡。
- 修复:`setZValue(1 if node.get("type")=="row_bg" else 10)`。层级:row_bg(1) < 连线(5) < 节点(10)。
- 注意 `setZValue(10)` 在文件中有 2 处(不同类),patch 要带上下文。

## 3. dirname 层数铁律(第 3 次确认)

`simulink_module.py` 在 `tools/gui/`,`os.path.dirname(os.path.abspath(__file__))` 2 层只到 `tools/`。
**仓库根必须 3 层 dirname**。本次踩坑:`_load_skill_library_groups()` 用 2 层 → 路径 `tools/flows/atomic_skill_tokens.json` 不存在 → try/except 吞异常 → 模块库技能分组 0(无报错!)。诊断:直接调函数看返回值,别信 LIBRARY 静态检查。

## 4. 原子技能 → W²-VLA Token 工程化链路(2026-08-09 落地)

```
dds-atomic-api.php (242 条技能, 9 大类)
  → flows/gen_atomic_conditions.py → atomic_skills_conditions.json (242 条件, 11 通道模态编码)
  → flows/gen_skill_tokens.py → atomic_skill_tokens.json (242 技能 × 6 元组 Token)
  → flows/gen_atomic_flow.py → atomic_conditions_flow.json (Simulink DAG: 9 row_bg + 242 条件节点)
```

- **6 元组 Token**(W²-VLA Latent Modeling Tokens 思想):`[SKILL_ID] [SEMANTIC] [SCENE] [STAGE] [MATURITY] [CoT]`,每 token 配 dimensions(id 64/semantic 384/scene 32/stage 16/maturity 8/cot 256)。
- **模态编码固定 11 通道**:image/force/pose/tactile/joint/pointcloud/temp/signal/code/cad + state_2d 兜底(无模态匹配时 state_2d=1)。生成器里 `enc` dict 必须先初始化 11 键,否则部分技能变 11、部分 10 → 结构不一致。
- **模块库组件区**:`_load_skill_library_groups()` 模块加载时 `LIBRARY += ...`(try/except 包住,缺文件不崩)。分组名 `("skill", f"🧩 原子技能 · {cat} ({len})", entries)`,每条 params 含 skill_id/tokens/action/modalities/encoding/gate。
- **skill 节点**:NODE_TYPES 加 `"skill": {"cn": "原子技能", "color": "#00d4aa"}`,icon 映射加 `"skill": "🧩"`。双击 → `_export_skill_action`(单技能 → `flows/action_<id>.json`);`export_all_skill_actions`(画布全部 → `flows/actions_<ts>.json`,画板可加载)。
- **模态提取规则**(关键词→通道):图/视觉→image;力/力矩→force;位姿/手眼/6D→pose;触觉→tactile;关节→joint;点云/3D→pointcloud;温度→temp;信号/IO/到位→signal;ID/条码/扫码→code;CAD/图纸→cad。
- **中文语义切词**:技能名按 `/`、`、`、空格拆短语 + 定义取 6-12 字长短语,别用 2-6 字粗切(出"等精_密来料"这种碎词)。
- 数据源:技能 = `https://datadrive.world/api/dds-atomic-api.php`;条件 = dds-data-space.html 内嵌表(无独立 API,curl + regex 解析 `<tr><td>C001</td>` 行)。

## 5. 其他本 session pitfall

- **PyQt 类体缩进吞代码**:ConfigModule(studio.py 6513 区)里 `_on_style_changed` 方法后的大块代码缩进错误(8 空格=方法体),导致"基础配置/VLM/ActionHead 等 9 个组从不显示"。诊断:offscreen 实例化后 `findChildren` 为空 + 类内 `def` 行缩进检查。修复=块缩进改回 __init__ 级并移到方法定义前。**改前 git checkout 恢复,别在损坏文件上反复试**。
- **深色主题悬停黑字看不清**:模块库按钮 QSS `:hover { color:#1f2328 }`,`switch_theme` 的替换对里没有 `#1f2328 → #c9d1d9` → 深底黑字。修:替换对补 hover 文字色。
- **首页 VEH.0**:`_veh0_apply` 严格限定 parent 链经过 HomeWidget(objectName="home");通用编号分支必须跳过 `_holo_page_of(w)=="P00"`(未识别页,否则侧栏控件被编成 VEH.0)。
- **验证脚本模式**:offscreen 验证用独立子进程 `/tmp/hermes-verify-*.py` 创建→运行→清理;嵌套 execute_code 里子脚本**自带 tempfile import**(外层有不代表子进程有)。生成器验证在 /tmp 隔离副本运行,产物与提交版逐字节比对(确定性)。
- **清理多实例误杀最新进程**:`ps aux | grep studio.py` 会出现**两组**(`/bin/bash -lic` 壳 + `/usr/bin/python3 tools/gui/studio.py` 子进程)。用 `awk '$2 != <已知pid>'` 批量 kill 时,若只排除了 bash 壳的 pid 而没排除 python 子进程的 pid → **误杀刚启动的最新实例**。改:精确 `kill <python 子进程 pid>`,或按启动时间保留最新(`ps -o lstart`),杀完 `wc -l` 确认只剩 1 组再重启。

## 5.5 工作流 JSON 加载(load_flow_file)— 画布文件 ↔ 模块库

- `load_flow_file(path)`:解析 `{format:"zmax-simulink", nodes[], links[]}` → `add_node` 恢复节点(含 x/y/params/w)→ **连线恢复必须用 item 引用**:`fi = self._items.get(f_id); ti = self._items.get(t_id); self.add_link(fi, ti)`。直接传节点 id 或调不存在的 `_add_link` → **links=0 且无报错**(测试断言 `len(m.links)==5` 才发现)。
- 模块库项三种点击行为(构建处 `if it.get("flow")` / `elif it.get("template")` / else 普通拖入):`"flow": "flows/system.json"` = 点击加载用户保存的画布 JSON;`"template"` = 点击加载 REFERENCE_APPS 模板。用户保存的画布(`💾 保存工作流 JSON` → flows/)可这样挂进模块库。
- 用户要求"画布上所有模块必须来自模块库" → 检查 REFERENCE_APPS 每个模板节点名是否都在 LIBRARY(offscreen 打印缺失清单),缺的补 LIBRARY 项。
- 改名/删节点三处同步:节点名出现在 REFERENCE_APPS 模板 + LIBRARY 项 + 模板 layout 数组,改一处必改三处;LIBRARY_SEQ 按 name 为 key 自动跟随,不用手动改序号。
- 总系统类模板用户会要求"删功能块只留骨架"(如 SYS2云端训练→部署→SYS1):直接重写 REFERENCE_APPS 条目,保留 LIBRARY 项,删 LIBRARY 里多余按钮项(template/flow 项)但**保留模板**供画布加载。

## 6. WSLg 窗口"看不到"三连查(2026-08-09,控制台启动)

- 用户"没看到/你没启动"但进程在跑:①`xdotool search --name "XSpace Studio"` 查窗口存在 ②`xdotool getwindowgeometry` 看 Position —— **负值巨大(如 -32692,-32650,接近 16 位整数边界)= Xwayland 坐标溢出,窗口在屏幕外**,不是没启动。
- 修复:①studio.py main() 里 `win.setGeometry(60,40,1400,900)` 兜底(show 之前,`QGuiApplication.primaryScreen()` 取屏);②或 `QT_QPA_PLATFORM=wayland /usr/bin/python3 tools/gui/studio.py` 直接走 wayland(compositor 管坐标不飞屏;日志的 libEGL/ZINK 警告是软件渲染噪音,可忽略)。
- xdotool `windowmove` 对飞屏窗口无效(WM 拦截),resize 有效——别在移动上耗时间,直接换 wayland 平台重启。
- 进程健康判定:`ps -o etime,%cpu -p <pid>` + 无崩溃 traceback = 窗口在;`xwininfo` 在 WSLg wayland 下不可用是正常的;wayland 平台窗口 xdotool 搜不到也正常(隔离)。

## 8. 场景系统(2026-08-09 老倪+web 协作落地)— 场景 node → ECS 可视化

### 协作分工(web 分身 + 静静)
- **web 做数据**:`flows/scene_skills_3scenarios.json`(SCN-01 插拔 / SCN-02 搬运 / SCN-03 光学检测;每场景含 description/layout/dimensions/performance/process_steps(5步,每步 atoms 引用原子技能)/key_atoms/quality_gates)+ 模块库 🏭 场景(3) 分组。
- **静静做 GUI 集成**:open_scene(ECS 链接)+ _build_scene_flow(节点链)+ scene.html(ECS 可视化页)。
- ⚠️ **用户/web 可能实时编辑同一文件**:本 session 我插入场景分组时用户也在编辑 → 三处场景条目缺闭合 `}`(desc 行 `},` 应为 `}},`)→ SyntaxError。**编辑前先 `git status` + 读最新内容**;语法错先 ast.parse 定位行号再修,别整文件重写。

### 场景 node 链路
- NODE_TYPES 加 `"scene": {"cn": "场景", "color": "#ff9f43"}`,icon 映射加 `"scene": "🤖"`(原 🏭 已改)。
- **场景节点小机器人图标**(2026-08-09,用户参考 semipv.com 产品页):SimNodeItem.paint 里 `if t == "scene":` 分支,用 QPainter 在节点右上角画青色小机器人(天线竖线+小圆 → 圆角头+两眼睛点 → 身体圆角矩形 → 左右手臂斜线),配色 `#00d4aa`,`painter.setRenderHint(Antialiasing)`。icon 数据层同步 `"scene": "🤖"`。
- LIBRARY 分组 `("scene", "🏭 场景 (3)", [{"name": "🔌 插拔场景 · QSFP-DD", "params": {"scene_id": "SCN-01", ...}}])`。
- ⚠️ **场景分组位置 = 数据集分组下面(动态构建,最终方案)**:用户先要求"能明显看到"→ 移到 LIBRARY 第一组;后又明确要求"在数据集分组下面"→ **最终方案**:场景分组从 LIBRARY 静态数组**移出**,改为 LibraryPanel 构建时动态插入(数据集动态分组 `_dset_cands` 之后、`self.v.addStretch()` 之前,读 scene_skills_3scenarios.json 现构建 3 个 QToolButton,样式深色青绿 `#0d1117` 底 + `#00d4aa` 边框,点击 `open_scene(sid)`,按钮文本含 `🔌/🤖/🔍 SCN-xx 名称 · 成功率`)。**注意**:"LIBRARY 第一组"只是中间态,用户最终要的是数据集下面——新需求优先,references 旧指引作废。
- ⚠️ **动态分组按钮不进 `_lib_btns`**:LibraryPanel 动态 addWidget 的按钮不在 `_lib_btns` dict,offscreen 验证要**遍历 `lib.v` 布局**(`for i in range(v.count()): it=v.itemAt(i); w_=it.widget(); w_.text()`),找 text 含 `SCN-` 的按钮断言 3 个;别用 `_lib_btns` 查(查不到 → 误判"没加到")。
- ⚠️ **删除 LIBRARY 首部元素别误删 `LIBRARY = [` 行**:replace 锚点若以 `LIBRARY = [\n` 开头,删除分组时会把 `LIBRARY = [` 一起删掉 → 后续 `IndentationError: unexpected indent`。锚点从 `LIBRARY = [` 之后的元素开始;删完 ast.parse 验证;若已误删,`# 模块库...\nLIBRARY = [` 上下文补回。
- ⚠️ **场景双击最终行为 v3 (2026-08-09 晚, 用户两次纠正后定稿)**: ①v1 "打开链接+建节点链" → 用户"怎么还多子模块?不需要打开子模块,只要打开链接" → v2 只 `open_scene_link`; ②v3 用户"双击打开一个json文件的窗口,我可以点击上传,而且能看到上传的链接" → **`_open_scene` 弹 JSON 上传窗口**(详见 simulink-flow-json.md §2: QPlainTextEdit 预览可编辑 + QLineEdit 只读上传链接 + 📋复制 + 📤上传 + 🌐打开3D + ✖关闭), **不再直接建链/直接开链接**。模块库场景按钮点击 = `open_scene_link`(只开链接)。
- ⚠️ **open_scene_link 最终实现 (cmd.exe start + POST, 2026-08-09 晚)**:
  1. **WSL 里 QDesktopServices.openUrl 找不到浏览器**(日志 "Unable to detect a web browser")→ 必须 `subprocess.Popen(["cmd.exe", "/c", "start", "", url])` 用 Windows 默认浏览器。
  2. **先 POST 场景 JSON 到 ECS** `https://datadrive.world/scene-api.php/<insert|handle|aoi>`(web 格式 `{name, skills, specs:{success_rate 小数 0.995, cycle_time}, kpi}`,urllib.request POST)→ 再 `cmd.exe start` 打开 3D 链接。success_rate 解析: `re.search(r"\d+(\.\d+)?", "≥99.5%")` 取 99.5 → `/100` → 0.995; cycle_time 同样正则取 3.5。
- **scene-api.php ECS 端点坑 (2026-08-09)**:
  - **404 = 端点根本没部署**(web 分身说"就绪"但实际没 scp 上)。查 ECS `ls /www/wwwroot/datadrive.world/scene-api.php`,自己写(scene-api.php: parse_url basename 取类型 → 校验 insert/handle/aoi → json_decode php://input → file_put_contents `scenes/scene_{type}.json` → 返回 {ok,saved,url}; 带 CORS 头 + OPTIONS 预检)。
  - **500 = scenes 目录权限**: PHP-FPM 以 `www` 用户跑,root 建的目录 `mkdir 755` www 写不了 → `chown -R www:www /www/wwwroot/datadrive.world/scenes`。日志定位: `/www/wwwlogs/datadrive.world.error.log` 里 "Failed to open stream: Permission denied"。
  - 路径型 URL `/scene-api.php/insert` 由 nginx fastcgi PATH_INFO 解析,宝塔默认支持; 404 时查 error.log "Primary script unknown"。
  - 验证: 公网 POST 3 端点 200 + 保存文件可读(内容 name 一致) + 负向(缺 name→400, 非法类型→400)。
- **⚠️ ECS 链接已从 2D scene.html 升级为 3D scene-3d.html(2026-08-09 晚,web 协作)**:open_scene 的 URL 现为 `https://datadrive.world/scene-3d.html?scene=<k>`,映射 `{"SCN-01": "insert", "SCN-02": "handle", "SCN-03": "aoi"}`(SCN 前缀 → 小写英文场景键)。旧 `scene.html?scene=&json=<base64>`(2D 卡片式)仍部署在 ECS 但不再是主入口。
- **scene-3d.html 自己写(web 的 4090 SCP 不通时)**:Three.js CDN(jsdelivr three@0.160 + OrbitControls.js)+ 简易 6 轴机械臂(圆柱/方块拼装:底座→腰→肩→大臂→肘→小臂→夹爪,材质 #00d4aa 青绿)+ 工件按场景切换(insert=QSFP模块+笼子 / handle=料盘+12槽 / aoi=检测台+转位台)+ 性能指标面板 + 底部场景切换按钮。部署同 ECS:scp → `/www/wwwroot/datadrive.world/scene-3d.html` → chmod 644 → 公网 3 链接 HTTP 200 验证(字节数与本地一致)。
- web 分身建 3D 页的参考链接:`https://datadrive.world/scene-3d.html?scene=insert|handle|aoi`(老化箱·QSFP28·力控 / 料盘·12槽·10kg / 7检测位·2μm)。
- **open_scene 必须兼容双结构**(web 场景库 vs 本地 scenes.json):`s.get("id") or s.get("scene_id")`、`scene.get("process_steps") or scene.get("process")`、`scene.get("performance") or scene.get("metrics")`。**`scene["scene_id"]` 硬编码会 KeyError**(web 结构用 `id`)——本 session 连续 4 处 KeyError 才全改完(_build_scene_flow 里 4 处硬编码)。

### 原子按钮场景优先 + 自动推荐(2026-08-09 改造)
- ⚠️ **v4 为最终版(2026-08-09 下午)**:用户"重来"后,open_atomic_skill_flow **不再弹选择框**,打开即一键建 SCN-01/02/03 三场景全链。v2 弹窗版(场景大按钮+推荐勾选)已被取代,references 旧流程作废。
- **v4 全链结构**(用户逐步确认的最终形态):
  1. 每场景:`scene` 节点(🔌/🤖/🔍 图标)→ atoms 去重后的 `skill` 节点序列(竖排)→ `coord_overlay` 结构条件(每场景一个)
  2. **3 个结构条件 → 汇聚 1 个共用 `system` SYS1 动作节点**(用户明确"用一个系统1就行了"——不是每场景一个 SYS1)
  3. **SYS1 → A001~A010 共 10 个 `action` 输出节点**(用户明确"A00~A10 全都是系统1的输出";A 系列名:A001 精密对准/A002 插入拔出/A003 压装扣合/A004 旋拧锁付/A005 扭矩角度/A006 轨迹加工/A007 点胶涂布/A008 贴标贴装/A009 撕膜贴膜/A010 锡焊钎焊;每节点 `action_out=/dds/action/a00x`)→ 外加 1 个 `📤 Action 汇总`(`/dds/action/scn_all`)。
  4. 实测 38 节点:3场景+20技能+3结构条件+1SYS1+11action。
- **⚠️ 布局间距铁律(用户"纵向太拥挤,要拉开距离,别重叠")**:技能节点间距 56→**90**(节点高 50,空隙 40);场景行距 250→**680**(SCN-01 有 7 技能,7×90=630 < 680 不跨行;250 时 7×56=392 已超 → 跨行重叠)。结构条件 y 对齐技能列中部(`_row_y + 200`)。**验证**:offscreen 全量两两节点检查 `abs(dx)<100 and abs(dy)<60` 计数必须为 0。
- 弹窗版(v2)要点(若用户回退要求):场景大按钮卡片(3 QPushButton 横排含成功率,选中青色高亮)+ 推荐技能勾选(process_steps.atoms 去重 + key_atoms)+ 工艺指标预览。
- 推荐数实测(v2):SCN-01 插拔 9 技能 / SCN-02 搬运 6 / SCN-03 检测 7。
- **⚠️ 弹窗深色主题白字铁律**(仍适用任何 QDialog):深色主题下默认 QLabel/QComboBox 黑字看不清(用户明确报"字体是黑色,看不清,要改成白色")。必须 `dlg.setStyleSheet(""" QDialog{background:#0d1117;} QLabel{color:#e6edf3; font-size:12px;} QComboBox{background:#161b22; color:#e6edf3; border:1px solid #30363d;} QComboBox QAbstractItemView{background:#161b22; color:#e6edf3; selection-background-color:#0d3b33;} QCheckBox{color:#e6edf3;} QPushButton{background:#21262d; color:#e6edf3; border:1px solid #30363d;} """)`。子控件下拉列表必须给 `QAbstractItemView` 设背景色(否则下拉项黑字黑底)。
- 场景 JSON 传 ECS:scene.html 读 `?scene=&json=`(base64url),JS `b64u()` = decodeURIComponent(atob(...));无 json 参数时 fetch `/api/scenes.json` 兜底渲染。Simulink 端 `base64.b64encode(json.dumps(scene, ensure_ascii=False).encode())` + `urllib.parse.quote` 拼 URL。

### ECS 部署
- `scene.html` + `api/scenes.json` scp 到 `/www/wwwroot/datadrive.world/` → **chmod 644**(scp 保留 600 → nginx 403)。
- 验证:公网 `https://datadrive.world/scene.html` 200 + `api/scenes.json` 200。
- 页面深色主题与 dds-data-space.html 一致(#0d1117 背景/#00d4aa 主色/卡片式布局/场景 tab 切换)。

## 7. ECS relay/ws 服务宕机恢复

- 现象:WSClient 报 `Handshake status 502 Bad Gateway`(不是超时)= nginx 反代 502 → 后端进程挂了(relay 39053 和/或 ws_relay 8766)。
- 恢复:`ssh root@39.102.211.79` → `cd /root/zmax-relay && nohup python3 zmax_relay.py & nohup python3 ws_relay.py &` → 验证 `curl 127.0.0.1:39053/api/health`(200)+ 公网 WS 握手(101)。
- 控制台 WSClient 5s 自动重连,服务恢复后无需重启 GUI。

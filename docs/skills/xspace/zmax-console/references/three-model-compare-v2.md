# 三模型对比·LEW旁路·性能扩展·连线标签 — 2026-08-05 下半场 (commits dfe153e0/f8334840/dacf60b9)

承接 SKILL.md「🔬 三模型对比」章节。本文件记录该章节之后的下半场迭代细节。

## 🌐 LEW 旁路拓扑修正 (老倪: "leworldmodel为什么直接链接Action Head呢? 为什么SmolVLM的输出没有链接leworldmodel呢? 之前不是定义的3层潜在空间交叉注意么?")

- **官方实现 (world_model_le.py:326-363)**: `LeWorldModel.forward(videos, actions)` — 输入是**原始视频帧 + 动作序列** (训练时用真值动作, modeling_smolvla_lew.py:208-217 传 videos_tensor+actions_tensor_wm), **不是 DiT-B 输出**。内部: SigLIP 编码视频帧 CLS embedding → action_encoder 编码动作 → ARPredictor 自回归预测下一帧 → L1 loss。
- **"3层潜在空间交叉注意" 真相 (87-110行)**: ConditionalBlock 是 **AdaLN-zero 条件调制** (非标准 cross-attention): 条件 c (动作嵌入) 经 adaLN_modulation 生成 shift/scale/gate 六参数调制每层。条件源 = 动作, 不是 DiT 输出。
- **画布拓扑修正**: LEW 从"串行在 DiT 后"改为**旁路**: 数据→LEW("视频+动作")→ActionHead·LEW("世界预测"), 主链路 SmolVLM2·LEW→DiT-B·LEW→ActionHead·LEW→训练 **并列** (22条连线)。LEW 不接 DiT 输出; SmolVLM 文本侧输出也不直接进 LEW (LEW 自带 SigLIP 视觉编码器, 构造时传入 vision_encoder)。
- **教训**: 画架构图/节点拓扑前必须读官方 forward 确认真实数据流, 别按直觉把"世界模型"画成串行; 条件调制 (AdaLN) ≠ cross-attention, 用户提"3层交叉注意"时先查代码再落笔。

## 🔬 模型性能对比扩展 (老倪: "除了loss曲线, 还有什么能对比模型的性能呢? 也需要增加")

- **对比维度 (除 loss 曲线外)**: ① 动作轨迹对比 (预测 vs 专家真值逐帧波形) ② 逐帧误差曲线 (MSE over frames) ③ 误差分布 P50/P90 (长尾) ④ 动作平滑度 (相邻预测差分 std, 真机抖动) ⑤ 收敛速度 ⑥ 验证集曲线 (过拟合)。
- **落地**: compare_models.py eval_policy 新增采集 `traj_pred/traj_gt` (逐帧轨迹, 限120帧) + `frame_err` (逐帧MSE) + `mse_p50/mse_p90` + `smoothness` (np.diff std); res dict 全带。ModelCompareDialog 加「📉 逐帧误差曲线」err_scope (ScopeWidget 每模型一条) + 表格加 误差P50/误差P90(长尾)/动作平滑度 3 行 + bars 5→8 指标; 旧数据缺字段 get 兜底显示 "-" 不崩。
- **⚠️ 对比报告是文件快照**: 对话框读 reports/model_compare_<ts>.json 最新文件 — **旧脚本生成的报告没有新字段 → 用户看到"还是只有loss"**。改了 compare_models.py 必须重新跑评估 (`tools/compare_models.py --frames 60`) 生成新报告, 光改代码不重跑等于没改 (2026-08-05 实测踩过)。
- **实测参考 (4060, 60帧)**: ACT MSE=1.40 P90=2.63 平滑度=0.036 延迟6.4ms vs SmolVLA+LEW MSE=1.07 (更准) P90=2.31 平滑度=0.204 (抖动大5.7x) 延迟470ms。

## 🏷 连线数据流标签 (老倪: "为什么 metaworld数据直接链接VAE编码器呢? 有什么直接输入呢?")

- **add_link(src, dst, label=None)** → link["label"]; REFERENCE_APPS link_specs 支持 (fi, ti, "标签") 三元组, load_reference_app 用 `for fi, ti, *label in link_specs` 解包。
- **SimLinkItem.paint 画标签**: link.get("label") → `path.pointAtPercent(0.5)` 中点, 半透明黑底 (QColor(0,0,0,160)) + 白字 (Consolas 7pt), 不干扰连线。
- **metaworld 数据节点三路输出** (官方 modeling_act.py 前向): (0,1)"图像"→ResNet18 · (0,2)"动作"→CVAE (**vae_encoder 输入是 ACTION 不是图像**, 415行 action_embed) · (0,3)"状态"→Encoder (464-465行 encoder_robot_state_input_proj); (2,3)"潜变量" CVAE→Encoder · (1,3)"图像特征" ResNet18→Encoder; SmolVLA 路 (0,8/12)"图像+状态"→SmolVLM2 · (8,9/12,13)"多模态embeds"→DiT-B。**用户问"为什么X连Y"时, 先读官方 forward 确认各模块真实输入, 再回答 — 别凭直觉**。

## 🧹 删除双模型对比 (老倪: "那对比, 和 三模型对比, 是不是重复了?")

- **双模型对比 = 三模型对比真子集** (SmolVLA+LEW 分支相同) → 删「⚔️ 对比」: REFERENCE_APPS 模板 + LIBRARY 条目 + btn_compare 按钮 + open_compare 方法 全删, 只留「🔬 三模型对比」+ btn_compare3 (单入口铁律: 一个功能一个入口, 绝不重复)。
- **⚠️ 删除入口四件套**: ① REFERENCE_APPS 模板 ② LIBRARY 模块库条目 ③ 按钮 mk_btn + tl/tl2.addWidget ④ open_xxx 方法。**漏删按钮 → 按钮还在但模板没了, 点击报"模板加载失败"** (2026-08-05 实测半删状态); 漏删方法 → AttributeError。grep 检查: `grep -n "open_compare\b\|btn_compare\b"` (注意 open_compare3/btn_compare3 是合法保留, 用 \b 边界)。
- **_compare_load_hint 保留** (三模型 open_compare3 复用同一气泡指引)。

## ✅ offscreen 验证两坑 (2026-08-05 实测)

- **验证脚本必须 monkeypatch 模态框**: `sm.SimulinkModule._qmsg = lambda *a,**k: None` + `_qmsg_yes = lambda *a,**k: True` 放 import 之后 — load_reference_app 有节点时弹 _qmsg_yes 确认, offscreen 下 exec_ 永远阻塞 → 脚本 timeout 60s (2026-08-05 实测踩过)。
- **execute_code 的 subprocess 默认 sys.executable 是 Hermes venv python (无 PyQt5!)**: 验证脚本若 `subprocess.run([sys.executable, path])` 会 ImportError/exit 1。**必须显式 `subprocess.run(["python3", path])`** (系统 python3 才有 PyQt5/numpy)。execute_code 内跑 GUI 验证用系统 python3, 别用 sys.executable。

## 🗄 ECS nginx+relay 双挂自愈 (老倪: "采集查询失败, 报的红色字体错误")

- **症状**: 控制台 Simulink 采集状态条红字"查询失败" = 轮询 `https://datadrive.world/api/relay/status` 失败。
- **诊断顺序**: ① `curl -s -o /dev/null -w "%{http_code}" https://datadrive.world/` = 000 + `curl github.com` = 200 → ECS 服务层问题 (网络正常) ② `ping 39.102.211.79` 通 = 主机活着 ③ SSH: `systemctl status nginx` = inactive/dead + `ps aux | grep [z]max_relay` 无进程 → 双挂。
- **修复**: `systemctl start nginx` (systemd 版) + `/www/server/nginx/sbin/nginx` (宝塔版, 443 监听, **systemd nginx 只 include /etc/nginx/conf.d 不加载宝塔 vhost → 无 443 监听**) + `cd /root/zmax-relay && bash start.sh` (relay 重启)。验证: 本地 `curl 127.0.0.1:39053/status` + 公网 `curl https://datadrive.world/api/relay/status` 双通。
- **⚠️ nginx 启动报 duplicate location 先 grep 当前配置**: 错误日志里的 duplicate location "/orin_realtime.jpg" 可能是历史遗留 (08-02/03 记录), 当前配置已无此段 — 别被旧日志误导, 看 `ss -tlnp | grep :443` 实际监听 + `nginx -t` 当前配置。

## 🧠 LeWorldModel CrossAttention K/V 注入 (老倪: "action 与潜在空间做真正的 cross-attention (K/V 注入)", commit 037ab5e6)

用户连续追问 LEW 的 action 输入机制后明确要求: **不要 AdaLN 调制, 要真 cross-attention**。落地:
- **world_model_le.py 新增两类**:
  - `CrossAttention(dim, heads, dim_head)`: Q=帧嵌入(潜在空间) · K/V=动作嵌入 — `to_q/to_k/to_v` 三个 Linear + norm_q/norm_kv + F.scaled_dot_product_attention (非因果)。**与 AdaLN 的本质区别: action 直接作为 attention 键值参与, 不是生成 shift/scale/gate 参数**。
  - `CrossConditionalBlock`: ①自注意力(帧内 norm1) ②交叉注意力 `x + self.cross_attn(self.norm2(x), c)` ③MLP(norm3) — 三残差块。
- **Transformer/ARPredictor/LeWorldModel 加 `attn_mode="adaln"|"cross"` 参数** (默认 adaln 保持兼容, cross 时 block_cls=CrossConditionalBlock)。
- **configuration_smolvla_lew.py 加 `lew_attn_mode: str = "adaln"`**; modeling_smolvla_lew.py 透传 `getattr(config, "lew_attn_mode", "adaln")`。
- **单测 6/6** (venv torch): CrossAttention 形状 / CrossConditionalBlock / Transformer(cross 全层 CrossConditionalBlock) / Transformer(adaln 兼容) / LeWorldModel 全链路 forward(videos,actions) loss 标量 / rollout。⚠️ 测试用 FakeVisionEnc 模拟 SigLIP: `config.vision_config.hidden_size` 必须与实际 proj 输出维度一致 (32→LeWorldModel.projector 32→64), 不一致报 `mat1 and mat2 shapes cannot be multiplied`。

## 🧩 ARPredictor 拆解成画布子模块 (老倪: "ARPredictor Transformer 还能拆解出来么?")

- **官方结构 (world_model_le.py)**: LeWorldModel = ①SigLIP帧编码 (encode_frame: vision_encoder+projector) + ②ActionEmbedder (Conv1d+MLP SiLU) + ARPredictor(pos_embedding → Transformer[input_proj/cond_proj/×N ConditionalBlock/norm/output_proj])。
- **LIBRARY 加「🌐 LeWorldModel·子模块」分类 6 条目**: 🖼SigLIP帧编码 / 🎛Action Embedder / 🔤位置编码 / 🔀输入·条件投影 / 🧠CrossAttn块×N (depth 6 heads 8) / 📤输出投影 — 与 ACT·子模块同模式, 供逐步搭建。

## 🎛 Simulink 子系统顶层总系统 (老倪: "还需要一个顶层系统, 参考 Simulink... 用一个模块表示总系统; 双击打开后可以看到三条线", commit 037ab5e6)

- **REFERENCE_APPS 加「🎛 总系统·三模型对比」3节点**: 📦metaworld数据 → 🔬总系统·三模型对比 (params: `{"subsystem": "🔬 三模型对比", "type_label": "Subsystem"}`) → 📊对比评估Scope; links (0,1,"数据")(1,2,"评估"); layout 单行三节点。
- **on_node_activated 最前面加 subsystem 分支** (优先于 source/switch/环节匹配): `if params.get("subsystem"): self._open_subsystem(node); return`。
- **_open_subsystem(node)**: 保存顶层 flow dict (nodes+links+sim) 到 `self._subsystem_stack` (init 兜底 getattr) → load_reference_app_by_name(sub_name) (失败则 pop 回滚) → `_update_back_btn()` → 日志指引 + QTimer _compare_load_hint。
- **back_to_subsystem()**: 栈空则"已在顶层"; 否则 pop 栈顶 → load_flow 恢复 (位置/连线全回) → 栈空时 `_subsystem_active=False` → _update_back_btn。
- **工具栏 btn_back "⬅ 返回总系统"** (#3fb950) 初始 `setVisible(False)`; `_update_back_btn()` 按 `bool(self._subsystem_stack)` 显隐; load_flow 末尾也调 (加载顶层时自动隐藏)。
- **验证 (offscreen 5/5)**: 顶层3节点 → on_node_activated 展开 18节点22连线 + btn_back 可见 + 栈深1 → back_to_subsystem 恢复3节点 + 栈空 + 按钮隐藏 → 可嵌套往返。

## 🖱 参考应用条按钮挤压隐藏 + 显眼入口 (老倪两次反馈 "顶层总系统 没有啊")

- **根因①: 参考应用条 9 个模板挤单行 QHBoxLayout (fixedHeight 38)**, 后面的「🎛 总系统」「🔬 三模型对比」被挤压到视觉消失 — 按钮对象存在 (offscreen 断言 isVisible/geo 都对!) 但用户看不到。**改 QScrollArea 横向滚动**: ra.setFixedHeight(44) + `ra_scroll = QScrollArea(); setWidgetResizable(True); setFixedHeight(32)` + inner QWidget+QHBoxLayout 装按钮 + `ral.addWidget(ra_scroll, 1)`。QScrollArea 顶部已 import (16行), 别函数内重复 import。
- **根因② (第二次反馈后): 功能藏在滚动条/参考应用里 = 没有显眼入口**。老倪期望像「🔬 三模型对比」那样在第二行工具栏有按钮。加 `btn_topsys "🎛 总系统"` (#a371f7) → open_topsys(): 确认清空 → load_reference_app_by_name("🎛 总系统·三模型对比") → 日志 + `_topsys_hint()` (金框高亮总系统块 + 气泡 "👆 双击金色高亮...展开三条训练线")。
- **通用教训 (2026-08-05 两次踩)**: 新增入口类功能, 默认就要给**第二行工具栏按钮** (老倪的视线焦点), 别只放参考应用滚动条/模块库 — 用户找不到 = 没做。验证时除了断言按钮对象存在, 还要渲染采样像素或确认用户可见路径 (offscreen 按钮 geo 正确 ≠ 用户看得到)。

## ✅ 验证脚本附加坑 (2026-08-05 实测)

- **execute_code 里 b''' 字节字面量不能含中文** (SyntaxError: bytes can only contain ASCII literal) — 生成验证脚本用 `os.write(fd, script.encode())` (普通字符串 + encode), 别用 b''' 包裹含中文的脚本。
- **系统验证规范 (Hermes)**: 临时验证脚本必须 tempfile.mkstemp 生成 (OS-safe 路径 + hermes-verify- 前缀), 跑完 os.remove 清理 — 系统会检查 /tmp/hermes-verify-*.py 残留并标记 stale。**留 25 个验证脚本不清理 → 系统持续报验证 stale**。GUI 验证用系统 python3, torch 机制验证用 .venv/bin/python, 一个 wrapper 脚本里 subprocess 分开跑两个子脚本。

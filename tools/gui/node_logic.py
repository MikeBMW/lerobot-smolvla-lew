# -*- coding: utf-8 -*-
"""
══════════════════════════════════════════════════════════════════
Z-MAX 节点逻辑库 (Node Logic) — 每个节点的可编辑逻辑
══════════════════════════════════════════════════════════════════

🛠 使用规则 (重要, 请先读):
  · 本文件是「节点背后的逻辑」— 双击节点运行、右键节点查看的就是这里
  · 每个函数中间标有:
        # === ✏️ 可修改区 START ===
        ... 这一段 = 你可以随便改 (参数/日志/判断逻辑)
        # === ✏️ 可修改区 END ===
  · 可修改区之外 (函数签名 / 开头结尾) = 🔒 框架区, 不要动
    — 改了可能导致节点无法运行, 保存时会警告
  · 保存后立即生效 (热重载, 无需重启控制台)
  · 「恢复默认」= 回到出厂模板

📖 节点 = 函数 对照:
  · 环节节点 (双击运行): 采集 / 训练 / 验证 / 集成 / 部署 / 推理
  · 结构节点 (右键查看): 📦metaworld数据 / ResNet18 / CVAE / Encoder / Decoder / ActionHead / Ensemble
══════════════════════════════════════════════════════════════════
"""
import importlib
import inspect
import os
import time

_LOGIC_FILE = os.path.abspath(__file__)

# ── 🔒 框架区: 注册表 (勿改) ──────────────────────────────────────
NODE_LOGIC = {}   # 语义key → {match:[关键字], fn, doc}
NODE_ORDER = []   # 注册顺序 (UI 列表展示)
_SOURCE_CACHE = {}  # key → 用户修改后的源码 (get_node_source 优先取)


def _reg(key, matches, doc, fn):
    NODE_LOGIC[key] = {"match": matches, "fn": fn, "doc": doc}
    NODE_ORDER.append(key)


def match_node(name):
    """节点名 → 语义key (最长关键字匹配, 避免「训练」抢先匹配「全新训练」)"""
    best, best_key = 0, None
    for key, info in NODE_LOGIC.items():
        for m in info["match"]:
            if m in name and len(m) > best:
                best, best_key = len(m), key
    return best_key


def execute_node_logic(module, node, label=None):
    """双击环节节点 → 执行节点逻辑 (用户可修改版). 未注册返回 None → 框架兜底"""
    name = node.get("name", "")
    key = match_node(name)
    if key is None:
        return None
    info = NODE_LOGIC[key]
    ctx = {"module": module, "params": node.get("params", {}),
           "log": getattr(module, "_log", None), "name": name, "label": label}
    return info["fn"](ctx)


def get_node_source(key):
    """语义key → 函数源码 (供编辑器展示)"""
    info = NODE_LOGIC.get(key)
    if not info:
        return None, None
    if key in _SOURCE_CACHE:
        return _SOURCE_CACHE[key], info["doc"]
    try:
        src = inspect.getsource(info["fn"])
    except (OSError, TypeError):
        src = None
    return src, info["doc"]


def get_node_location(key):
    """语义key → 代码位置 (path, line, modified) 供 VSCode 打开.

    path: 绝对路径 (原始=node_logic.py; 用户修改过=仍在 node_logic.py, 但逻辑是动态加载)
    line: 函数定义行号 (修改版为 None, 动态 exec 无行号)
    modified: True=用户改过(动态生效, 未落盘)
    """
    info = NODE_LOGIC.get(key)
    if not info:
        return None, None, False
    # 📂 外部源码映射优先 (left_right 等真实实现不在 node_logic.py, 2026-08-10)
    ext = globals().get("_EXTERNAL_LOC", {}).get(key)
    if ext:
        return ext[0], ext[1], False
    fn = info["fn"]
    modified = key in _SOURCE_CACHE
    path = getattr(fn.__code__, "co_filename", None)
    line = getattr(fn.__code__, "co_firstlineno", None)
    if not path or not path.endswith(".py"):
        path = _LOGIC_FILE
        line = None
    return path, line, modified


def get_node_external_symbol(key):
    """外部源码映射的真实符号名 (VSCode 定位显示用) — 无映射返回 None"""
    ext = globals().get("_EXTERNAL_LOC", {}).get(key)
    return ext[2] if ext else None


def get_external_source(key):
    """外部真实实现的源码块 (按符号截取, 只读参考) — left_right 等节点
    显示 modeling_left_right.py 的 class LeftBrainMLP 全文, 不是 node_logic 占位函数"""
    ext = globals().get("_EXTERNAL_LOC", {}).get(key)
    if not ext:
        return None
    path, line, sym = ext
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except Exception:
        return None
    # 🐛 2026-08-12 老倪: 用符号名定位 (sym="class RightBrainWM") — 映射行号错位时
    # 源码截取从空行开始 → 面板只显示"源码结束"标记 → 改用名称搜索, 行号仅兜底
    start = None
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s == sym or s.startswith(sym + "("):
            start = i
            break
    if start is None:
        start = max(0, line - 1)
    out = []
    for i in range(start, len(lines)):
        ln = lines[i]
        if out and (ln.startswith("class ") or ln.startswith("def ") or ln.startswith("@")):
            break  # 下一个顶层定义
        out.append(ln)
        # 符号体结束: 空行后出现顶格非空行 (缩进归零, 非注释/docstring)
        if i > start and not ln.strip() and i + 1 < len(lines):
            nxt = lines[i + 1]
            if nxt and not nxt[0].isspace() and not nxt.startswith(("#", '"""', "'''", "from ", "import ")):
                break
    if not out:
        return None
    return "\n".join(out) + f"\n\n# ── {sym} 源码结束 (文件 {os.path.basename(path)}:{start + 1}) ──"


def save_node_logic(key, new_code):
    """保存用户修改 → exec 原地替换函数 (即时生效, 无需重启/热重载).

    返回 (ok, msg, warn列表)
    """
    info = NODE_LOGIC.get(key)
    if not info:
        return False, f"未知节点逻辑: {key}", []
    try:
        # 语法检查
        compile(new_code, f"<node:{key}>", "exec")
    except SyntaxError as ex:
        return False, f"❌ 语法错误 (第{ex.lineno}行): {ex.msg}", []
    fn_name = info["fn"].__name__
    ns = {}
    try:
        exec(compile(new_code, f"<node:{key}>", "exec"), globals(), ns)
    except Exception as ex:
        return False, f"❌ 代码执行失败: {ex}", []
    new_fn = ns.get(fn_name)
    if new_fn is None:
        return False, f"❌ 新代码里找不到函数定义 def {fn_name}(...)", []
    # 原地替换: 注册表指向新函数 + 缓存源码 (simulink 侧同模块对象, 立即生效)
    NODE_LOGIC[key]["fn"] = new_fn
    _SOURCE_CACHE[key] = new_code
    return True, f"✅ 已保存并生效 ({fn_name})", []


def restore_default(key):
    """恢复出厂逻辑: 从文件重新 exec 取原始函数 (真实文件行号 + 清修改缓存).

    返回 (ok, msg)
    """
    info = NODE_LOGIC.get(key)
    if not info:
        return False, f"未知节点逻辑: {key}"
    fn_name = info["fn"].__name__
    try:
        with open(_LOGIC_FILE, encoding="utf-8") as f:
            code = f.read()
        ns = {"__file__": _LOGIC_FILE, "__name__": __name__}
        # filename=真实路径 → exec 出的函数 co_filename/co_firstlineno 指向文件真实位置
        exec(compile(code, _LOGIC_FILE, "exec"), ns)
        orig_fn = ns.get(fn_name)
        if orig_fn is None:
            return False, f"❌ 文件中找不到 def {fn_name}"
        NODE_LOGIC[key]["fn"] = orig_fn
        _SOURCE_CACHE.pop(key, None)   # 清修改标记
        return True, f"✅ 已恢复出厂逻辑 ({fn_name})"
    except Exception as ex:
        return False, f"❌ 恢复失败: {ex}"


def reload_node_logic():
    """热重载本模块 (保存后调用, 新逻辑立即生效)"""
    return importlib.reload(__import__(__name__))


def list_logic():
    """所有节点逻辑一览: [(key, match, doc)]"""
    return [(k, v["match"], v["doc"]) for k, v in NODE_LOGIC.items()]


# ════════════════════════════════════════════════════════════════
# ① 采集 — 拉取 Orin 真实数据 (relay → 修复 action → 落地)
# ════════════════════════════════════════════════════════════════
def node_collect(ctx):
    """① 采集 — Orin 真实数据拉取"""
    module = ctx["module"]
    log = ctx["log"]
    # === ✏️ 可修改区 START ===
    endpoint = "https://datadrive.world/api/relay"   # 数据中转端点 (ECS nginx 反代)
    fix_action = True          # action 恒等修复开关 (True=标准, False=保留原始 action)
    timeout = 8                # 网络超时秒数
    if log:
        log(f"📡 采集配置: {endpoint} · 修复action={fix_action} · 超时{timeout}s")
    # 想加自己的处理逻辑? 在这里写 (例如: 只收 n_joint==6 的包、记录来源统计)
    # === ✏️ 可修改区 END ===
    # 🔒 框架动作: 真实拉取 relay → 落地 (勿改)
    return module.on_collect(timeout=timeout, fix_action=fix_action, endpoint=endpoint)


# ════════════════════════════════════════════════════════════════
# ② 训练 — ACT 策略训练 (lerobot_train)
#   同时服务「🚀 全新训练」节点 (metaworld 全新训练) 与「② 训练」环节
# ════════════════════════════════════════════════════════════════
def node_train(ctx):
    """② 训练 — ACT/SmolVLA 策略训练 (参数在可修改区, 真实写入训练配置)"""
    module = ctx["module"]
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    steps = p.get("steps", 1000)     # 训练步数 (2026-08-06 正式对比 500 步) (4060 实测 ACT ~13步/s, 300步≈40s; SmolVLA 更慢)
    batch_size = 8                   # batch size (SmolVLA 显存小可改 1)
    lr = 1e-4                        # 学习率 (S3 真机微调用 1e-5)
    data_source = "auto"             # auto(画布switch决定) | orin(只拉真实) | metaworld(占位集)
    policy = p.get("policy", "act")  # act | smolvla_lew (⚔️ 对比模板两训练节点各设一种, 节点params指定)
    if log:
        log(f"🧠 训练配置: steps={steps} · batch={batch_size} · lr={lr} · 数据源={data_source} · policy={policy}")
    # 2026-08-06 老倪: 蒸馏 MLP / 官方专家 入画布
    if policy == "expert_mlp":
        import subprocess, sys as _sys, re as _re, json as _json
        log("🎓 专家蒸馏训练: 300 episodes 官方专家数据 → BC 蒸馏 MLP")
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # tools/gui → repo 根
        r = subprocess.run([_sys.executable, os.path.join(repo, "tools", "distill_expert.py")], capture_output=True, text=True, cwd=repo)
        tail = (r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr.strip()[-100:])
        log(f"  {tail}")
        # 📈 落曲线 (2026-08-07): epoch loss → Scope 对比图表可见 MLP 蒸馏进度
        try:
            pts = [(int(m[0]), float(m[1])) for m in _re.findall(r"epoch (\d+): loss=([\d.eE+-]+)", r.stdout)]
            os.makedirs(os.path.join(repo, "reports"), exist_ok=True)
            with open(os.path.join(repo, "reports", "train_curve_expert_mlp.json"), "w", encoding="utf-8") as f:
                _json.dump({"policy": "expert_mlp", "name": "MLP 蒸馏", "ts": time.strftime("%Y%m%d_%H%M%S"),
                            "curve": pts, "step_s": 0, "ckpt": "outputs/rl_peg/expert_mlp.pt",
                            "success": "抓起18/20 插入11/20 (55%)"}, f, ensure_ascii=False)
            log(f"📈 MLP 蒸馏曲线已存: reports/train_curve_expert_mlp.json ({len(pts)} epochs)")
        except Exception:
            pass
        return {"ok": True, "policy": "expert_mlp", "ckpt": "outputs/rl_peg/expert_mlp.pt"}
    if policy == "expert_policy":
        log("📏 官方专家基准: 非训练 (metaworld 内置规则策略), 成功率 19/20 抓起 17/20 插入 (85%)")
        # 📈 落基准数据 (2026-08-07): 让 Scope 对比图表把专家作为真值锚点显示
        try:
            import json as _json
            repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            os.makedirs(os.path.join(repo, "reports"), exist_ok=True)
            with open(os.path.join(repo, "reports", "train_curve_expert_policy.json"), "w", encoding="utf-8") as f:
                _json.dump({"policy": "expert_policy", "name": "官方专家", "ts": time.strftime("%Y%m%d_%H%M%S"),
                            "curve": [], "step_s": 0, "ckpt": "", "success": "85% (19/20抓起 17/20插入)"}, f, ensure_ascii=False)
        except Exception:
            pass
        return {"ok": True, "policy": "expert_policy", "success": "85%"}
    # 想改训练逻辑? 在这里写 (例如: 按数据帧数自动调整 steps)
    # === ✏️ 可修改区 END ===
    # 🔒 框架动作: 真实 lerobot_train (数据源智能选择, 勿改)
    return module.on_train(steps=steps, batch_size=batch_size, lr=lr, data_source=data_source, policy=policy)


# ════════════════════════════════════════════════════════════════
# ③ 验证 — Simulink 模型验证 (validate_flow --strict)
# ════════════════════════════════════════════════════════════════
def node_validate(ctx):
    """③ 验证 — 流程拓扑合规检查"""
    module = ctx["module"]
    log = ctx["log"]
    # === ✏️ 可修改区 START ===
    strict = True     # True=严格模式 (全部 8 项检查) / False=只查格式与连线
    if log:
        log(f"🛡 验证配置: strict={strict}")
    # === ✏️ 可修改区 END ===
    # 🔒 框架动作: 真实 validate_flow (勿改)
    return module.on_validate(strict=strict)


# ════════════════════════════════════════════════════════════════
# ④ 集成 — checkpoint 打包 → 上传 ECS 中转
# ════════════════════════════════════════════════════════════════
def node_integrate(ctx):
    """④ 集成 — 打包最新 checkpoint → 上传 ECS"""
    module = ctx["module"]
    log = ctx["log"]
    # === ✏️ 可修改区 START ===
    if log:
        log("📦 集成: 打包最新 checkpoint → 上传 ECS 中转 (cicd_deploy.py push)")
    # 自定义前置检查 (真执行): 例如要求训练产物存在才允许集成
    # import os
    # if not os.path.exists(os.path.expanduser("~/lerobot-smolvla-lew/outputs/train")):
    #     return False, "没有训练产物, 无法集成"
    # === ✏️ 可修改区 END ===
    # 🔒 框架动作: cicd_deploy.py push (勿改)
    return module.on_integrate()


# ════════════════════════════════════════════════════════════════
# ⑤ 部署 — ECS 部署状态 / 推送到产线
# ════════════════════════════════════════════════════════════════
def node_deploy(ctx):
    """⑤ 部署 — 部署状态检查与推送"""
    module = ctx["module"]
    log = ctx["log"]
    # === ✏️ 可修改区 START ===
    if log:
        log("🚚 部署: 检查 ECS 部署状态 (cicd_deploy.py status)")
    # 自定义部署前检查 (真执行): 例如要求 Orin 心跳在线才报告成功
    # import requests
    # try:
    #     o = requests.get("https://datadrive.world/api/relay/orin/status", timeout=5).json()
    #     if not o.get("online"):
    #         return False, "Orin 离线, 部署无意义"
    # except Exception as ex:
    #     return False, f"Orin 状态查询失败: {ex}"
    # === ✏️ 可修改区 END ===
    # 🔒 框架动作: cicd_deploy.py status (勿改)
    return module.on_deploy()


# ════════════════════════════════════════════════════════════════
# ⑥ 推理 — Orin 推理服务状态
# ════════════════════════════════════════════════════════════════
def node_mode_switch(ctx):
    """🔀 训练/推理模式开关 — 双击切换 train ⇄ infer, 激活路径金色高亮, 未激活灰显
    数据流: 📦数据源 → 🔀开关 → 🚀训练 | 📷推理(rollout)
    train → 训练节点激活(推理灰显); infer → 推理节点激活(训练灰显)
    真实实现: simulink_module.py _toggle_mode / _apply_mode_highlight / paint(mode_active 灰显)"""
    log = ctx["log"]
    node = ctx.get("node", {})
    p = node.get("params", {})
    mode = p.get("mode", "train")
    log(f"🔀 模式开关: 当前={'训练' if mode == 'train' else '推理'} (双击切换, 激活路径高亮)")
    return True


def node_infer_rollout(ctx):
    """📷 推理 (rollout) — 加载最新双脑 checkpoint → 仿真插拔 rollout → 评估+视频
    后台 worker: gen_insert_video.py (最新模型按 mtime 排序, 归一化从 preprocessor 读)
    输出: reports/insert_success_demo.mp4 → 自动发飞书 dataworld 群
    真实实现: simulink_module.py on_infer_rollout (_start_worker) + tools/gen_insert_video.py"""
    log = ctx["log"]
    node = ctx.get("node", {})
    p = node.get("params", {})
    log(f"📷 推理 rollout: policy={p.get('policy', 'left_right')} frames={p.get('frames', 60)} → 评估插拔成功率+视频")
    return True


def node_eval_state_space(ctx):
    """📊 模型评估 (状态空间) — Z700 双脑稳定性评估 (2026-08-12 老倪)
    指标: ①L2增益(左脑Lipschitz) ②BIBO(有界输入有界输出) ③自回归谱半径ρ(右脑预测误差)
    ④状态机覆盖(6阶段可达+成功率) ⑤李雅普诺夫势能 ⑥谱范数 ⑦潜空间频谱 ⑧接触分离 ⑨动作平滑度
    状态空间: X=[X_obs(43D), X_latent(潜), X_sm(6阶段状态机)]
    真实实现: tools/eval_state_space.py → reports/eval_state_space.json + 飞书"""
    log = ctx["log"]
    node = ctx.get("node", {})
    log("📊 状态空间评估: L2增益 → BIBO → 自回归ρ → 状态机覆盖 → 稳定性结论")
    return True


def node_spectral_norm(ctx):
    """🧮 谱归一化分析 — 左脑 MLP 逐层谱范数 σ_max + Lipschitz 上界 (2026-08-12 老倪)
    原理: ||f(x1)-f(x2)|| ≤ L·||x1-x2||, L = Πσ_max(W_i) (ReLU 导数 0/1 不放大)
    数据来自: 左脑权重 SVD (eval_state_space.py spectral_norm_analysis)
    双击 → 全面 Z 分析 (含本模块计算结果)"""
    log = ctx["log"]
    log("🧮 谱归一化: 左脑逐层 σ_max → Lipschitz 上界 (双击已触发 Z 分析)")
    return True


def node_gru_gate(ctx):
    """🧮 GRU 门控机制 — 右脑潜空间门控收缩分析 (2026-08-12 老倪)
    原理: 重置门 r=σ(W_hr·h) · 更新门 z=σ(W_hz·h); ρ(W_hz)<1 → 潜状态指数收敛防爆炸
    数据来自: 右脑 GRU 权重谱半径 (eval_state_space.py gru_gate_analysis)
    双击 → 全面 Z 分析 (含本模块计算结果)"""
    log = ctx["log"]
    log("🧮 GRU 门控: 右脑潜空间 ρ(W) 收缩分析 (双击已触发 Z 分析)")
    return True


def node_force_limit(ctx):
    """🧮 力幅值限幅 — 插入阶段动作饱和 → 临界阻尼估计 (2026-08-12 老倪)
    原理: 二阶系统 Mẍ+Bẋ+Kx=0, 阻尼比 ζ=B/(2√MK); 限幅 [-0.6,0.6] = 非线性阻尼 → ζ→1
    数据来自: rollout 动作差分 (eval_state_space.py force_limit_analysis)
    双击 → 全面 Z 分析 (含本模块计算结果)"""
    log = ctx["log"]
    log("🧮 力幅值限幅: 插入阶段饱和 → 临界阻尼 ζ 估计 (双击已触发 Z 分析)")
    return True


def node_eval_report_pdf(ctx):
    """📄 稳定性评估 PDF — 汇总报告节点 (2026-08-14 老倪)
    内容: 摘要结论 + 状态空间建模(公式) + 三工程图详释 + 九指标表 + 三模块公式 + 调优建议
    数据: reports/eval_state_space.json + 三张 png → gen_report_state_space.py → PDF → 飞书"""
    log = ctx["log"]
    log("📄 稳定性评估 PDF: 九指标+三模块+三图详释 → 汇总报告 → 飞书")
    return True


def node_ff_pd_control(ctx):
    """⚙️ 前馈 PD 控制器 — 顶层控制模型 (2026-08-14 老倪)
    思想: 系统 = 带前馈的增益调度 PID
      状态机 = 强力 P (e×Kp: delta=peg−hand, act+=delta*2.0)
      物理限幅 = 隐性 D 与饱和 (死区/限幅=非线性阻尼, 放弃 I 避免积分饱和)
      左脑 MLP = 前馈控制器 (直接预测动作, 偏差产生前给力)
      右脑 WM = 预测器 (预判接触提前减速)
    层级: ⚙️前馈PD=顶层控制模型, Z700双脑+状态机=底层执行模型
    数据: LeftRightPolicy 动作 → PD 分析 → 模型评估汇总 (ff_pd_analysis.py)
    双击 → 前馈 vs 纯 PD 对比仿真 + 图 + 飞书"""
    log = ctx["log"]
    log("⚙️ 前馈 PD: 增益调度 P + 隐性 D + 前馈预测 → 对比仿真 (顶层控制模型)")
    return True


def node_ff_ref_input(ctx):
    """📡 参考输入 u(t) — 前馈 PD 顶层系统输入 (2026-08-14 老倪)
    增益调度各阶段的期望: 目标位置/力参考, 误差 e(t) = 参考 − 实际"""
    log = ctx["log"]
    log("📡 参考输入 u(t): 目标位置/力参考 → 误差 e(t) 驱动增益调度 P 控制")
    return True


def node_ff_scope(ctx):
    """🖥 输出 Scope — 前馈 PD 顶层系统输出 (2026-08-14 老倪)
    y(t): 完成状态/误差曲线 (等效 PD 响应), 反映 Z700 子系统对参考输入的跟踪"""
    log = ctx["log"]
    log("🖥 输出 Scope: y(t) = Z700 子系统对参考输入的响应 (误差/完成状态)")
    return True


def node_z700_internal(ctx):
    """🔬 Z700 内部模块 (顶层只读展示) — 2026-08-14 老倪
    前馈PD顶层视角: 感知→双脑→接近→抓取→抬起→转移→插入→完成 模块链 (输入输出可见)
    双击 → 提示进入上方「🔬 Z700 子系统」完整画布 (训练/评估/交付全功能)"""
    log = ctx["log"]
    log("🔬 Z700 内部模块 (只读): 感知→双脑→状态机链 — 完整功能请双击上方 Z700 子系统块")
    return True


def node_infer(ctx):
    """⑥ 推理 — 产线推理服务状态查询"""
    module = ctx["module"]
    log = ctx["log"]
    # === ✏️ 可修改区 START ===
    if log:
        log("⚡ 推理: 查询 Orin 推理服务状态 (infer_count/延迟/心跳)")
    # 自定义推理检查 (真执行): 例如要求推理次数 > 0
    # === ✏️ 可修改区 END ===
    # 🔒 框架动作: Orin 状态查询 (勿改)
    return module.on_infer()


# ════════════════════════════════════════════════════════════════
# 📦 metaworld 数据 — 训练数据源 (hardware 节点)
#   双击=切换激活; 右键=查看/修改数据选择逻辑
# ════════════════════════════════════════════════════════════════
def node_metaworld_data(ctx):
    """📦 metaworld 数据 — 训练数据源选择"""
    module = ctx["module"]
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    source = p.get("source", "metaworld")   # metaworld(占位集) | orin(真实产线)
    frames = p.get("frames", 696)           # 期望帧数 (展示用)
    if log:
        log(f"📦 数据源: {source} · {frames}帧 (画布节点双击可切换)")
    # 数据源策略: 想强制某来源训练, 在「训练」节点的 data_source 里改
    # === ✏️ 可修改区 END ===
    # 🔒 框架动作: 激活数据源 (勿改)
    return module._toggle_source_node(ctx["name"])


# ════════════════════════════════════════════════════════════════
# 🖼 视觉主干 ResNet18 — 官方 ACT.backbone (特征提取)
# ════════════════════════════════════════════════════════════════
def node_resnet18(ctx):
    """🖼 视觉主干 ResNet18 — ACT.backbone → layer4 特征图 (B,C,H,W)"""
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    backbone = p.get("backbone", "resnet18")   # 主干网络
    pretrained = p.get("pretrained", True)     # 是否用 ImageNet 预训练权重
    if log:
        log(f"🖼 ResNet18: backbone={backbone} · pretrained={pretrained}")
    # 官方源码: self.backbone = ResNet18(pretrained) → 输出 512 通道特征图
    # === ✏️ 可修改区 END ===
    # 🔒 结构节点: 参数在「训练」时合并进 ACT 配置 (勿改)
    return (True, f"ResNet18 配置: {backbone} pretrained={pretrained}")


# ════════════════════════════════════════════════════════════════
# 🧬 VAE 编码器 CVAE — 官方 ACT.vae_encoder (潜变量分布 μ,logσ²)
# ════════════════════════════════════════════════════════════════
def node_cvae(ctx):
    """🧬 VAE 编码器 CVAE — 动作条件变分自编码器"""
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    use_vae = p.get("use_vae", False)       # 是否启用 VAE (False=确定性策略)
    latent_dim = p.get("latent_dim", 32)   # 潜变量维度 (官方默认 32)
    if log:
        log(f"🧬 CVAE: use_vae={use_vae} · latent_dim={latent_dim}")
    # 官方源码: self.vae_encoder = CVAE(latent_dim=32)
    # === ✏️ 可修改区 END ===
    # 🔒 结构节点: 参数在「训练」时合并进 ACT 配置 (勿改)
    return (True, f"CVAE 配置: latent_dim={latent_dim}")


# ════════════════════════════════════════════════════════════════
# 🔤 Transformer Encoder — 官方 ACT.encoder (状态+视觉特征融合)
# ════════════════════════════════════════════════════════════════
def node_encoder(ctx):
    """🔤 Transformer Encoder — 视觉特征 + 状态 → 上下文向量"""
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    dim_model = p.get("dim_model", 512)    # 模型宽度 (官方默认 512)
    n_heads = p.get("n_heads", 8)          # 注意力头数
    if log:
        log(f"🔤 Encoder: dim_model={dim_model} · n_heads={n_heads}")
    # 官方源码: ACT.encoder = nn.TransformerEncoder(...) 6 层
    # === ✏️ 可修改区 END ===
    # 🔒 结构节点: 参数在「训练」时合并进 ACT 配置 (勿改)
    return (True, f"Encoder 配置: dim={dim_model} heads={n_heads}")


# ════════════════════════════════════════════════════════════════
# 🔡 Transformer Decoder — 官方 ACT.decoder (动作序列生成)
# ════════════════════════════════════════════════════════════════
def node_decoder(ctx):
    """🔡 Transformer Decoder — 自回归生成动作 chunk"""
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    num_layers = p.get("num_layers", 6)    # 解码器层数 (官方默认 6)
    if log:
        log(f"🔡 Decoder: num_layers={num_layers}")
    # 官方源码: ACT.decoder = nn.TransformerDecoder(...) 生成未来 T 步动作
    # === ✏️ 可修改区 END ===
    # 🔒 结构节点: 参数在「训练」时合并进 ACT 配置 (勿改)
    return (True, f"Decoder 配置: layers={num_layers}")


# ════════════════════════════════════════════════════════════════
# 🎯 Action Head 4D — 官方 action_head (线性映射到动作空间)
# ════════════════════════════════════════════════════════════════
def node_action_head(ctx):
    """🎯 Action Head — 解码特征 → 关节动作 (维度=数据动作维度)"""
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    action_dim = p.get("action_dim", 4)      # ★ 4=metaworld(sawyer) / 6=真机Orin珞石
    chunk_size = p.get("chunk_size", 7)      # 每次预测的动作步数
    if log:
        log(f"🎯 ActionHead: action_dim={action_dim} · chunk={chunk_size} (真机Orin为6D)")
    # 官方源码: self.action_head = nn.Linear(dim_model, action_dim)
    #   输出维度自动取自数据特征, 训练数据决定, 改这里仅影响说明
    # === ✏️ 可修改区 END ===
    # 🔒 结构节点 (勿改)
    return (True, f"ActionHead 配置: {action_dim}D chunk={chunk_size}")


# ════════════════════════════════════════════════════════════════
# ⏳ Temporal Ensemble — 官方 ACTTemporalEnsembler (动作平滑)
# ════════════════════════════════════════════════════════════════
def node_ensemble(ctx):
    """⏳ Temporal Ensemble — 多步预测加权平均, 抑制抖动"""
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    coeff = p.get("coeff", 0.01)     # 平滑系数 (官方默认 0.01, 越大越平滑但延迟更高)
    if log:
        log(f"⏳ Ensemble: coeff={coeff}")
    # 官方源码: ACTTemporalEnsembler(coeff=0.01) — 指数滑动平均
    # === ✏️ 可修改区 END ===
    # 🔒 结构节点 (勿改)
    return (True, f"Ensemble 配置: coeff={coeff}")


# ════════════════════════════════════════════════════════════════
# 📊 Scope 示波器 — 训练效果观察 (Simulink Scope 对标)
# ════════════════════════════════════════════════════════════════
def node_scope(ctx):
    """📊 Scope 示波器 — 显示训练 loss 曲线/执行效果"""
    module = ctx["module"]
    log = ctx["log"]
    # === ✏️ 可修改区 START ===
    if log:
        log("📊 Scope: 打开示波器查看训练 loss 曲线 (Simulink Scope 对标)")
    # 想加通道? 在这里写 (例如: 训练完同时统计 action 输出范围)
    # === ✏️ 可修改区 END ===
    # 🔒 框架动作: 打开示波器对话框 (勿改)
    return module.on_scope()


# ════════════════════════════════════════════════════════════════
# 🧠 SmolVLM2-500M — SmolVLA 视觉语言主干 (多模态编码, 冻结/参与训练)
# ════════════════════════════════════════════════════════════════
def node_smolvlm2(ctx):
    """🧠 SmolVLM2-500M — 视觉语言主干 (SmolVLM2-500M-Video-Instruct)"""
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    freeze = p.get("freeze", True)      # True=冻结(VLM 只做编码) / False=参与训练(LEW 需要)
    smolvlm = p.get("smolvlm", "HuggingFaceTB/SmolVLM2-500M-Video-Instruct")
    if log:
        log(f"🧠 SmolVLM2-500M: freeze={freeze} · {smolvlm}")
    # 官方源码: modeling_smolvla_lew.py SmolVLALewPolicy — SmolVLM2 多模态编码
    #   视觉+语言 → 多模态 embeds → DiT 动作解码; LEW 分支要求 freeze=False
    # === ✏️ 可修改区 END ===
    # 🔒 结构节点: 参数在「训练」时合并进 SmolVLA 配置 (勿改)
    return (True, f"SmolVLM2: freeze={freeze}")


# ════════════════════════════════════════════════════════════════
# 🌀 DiT-B 动作解码 — SmolVLA action_model (扩散去噪生成动作块)
# ════════════════════════════════════════════════════════════════
def node_dit_b(ctx):
    """🌀 DiT-B 动作解码 — SmolVLA 扩散动作生成器 (含 base VLA 冻结版)"""
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    hidden = p.get("hidden", 256)       # DiT 隐藏宽度 (4060 精简 256)
    layers = p.get("layers", 1)         # 层数 (1=精简, 官方更多)
    timesteps = p.get("timesteps", 2)   # 推理扩散步数 (num_inference_timesteps)
    freeze = p.get("freeze", False)     # VLA-Touch base VLA 冻结版=True
    if log:
        log(f"🌀 DiT-B: hidden={hidden} · layers={layers} · timesteps={timesteps} · freeze={freeze}")
    # 官方源码: action_model_type="DiT-B" — 噪声预测网络, 条件=多模态 embeds
    #   VLA-Touch 中作 base VLA 冻结 (不训练, 只出粗动作给 Interpolant 精炼)
    # === ✏️ 可修改区 END ===
    # 🔒 结构节点 (勿改)
    return (True, f"DiT-B: hidden={hidden} layers={layers} freeze={freeze}")


# ════════════════════════════════════════════════════════════════
# 🌐 LeWorldModel — 世界模型旁路 (视频帧+动作 → 预测下一帧)
# ════════════════════════════════════════════════════════════════
def node_lew(ctx):
    """🌐 LeWorldModel — 潜空间世界模型 (SigLIP 编码→AdaLN-zero 调制→预测下一帧)"""
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    lew_loss_weight = p.get("lew_loss_weight", 0.1)   # 世界模型 loss 权重 (总loss=扩散+0.1×LEW)
    num_video_frames = p.get("num_video_frames", 2)   # 输入视频帧数
    if log:
        log(f"🌐 LeWorldModel: loss_weight={lew_loss_weight} · frames={num_video_frames}")
    # 官方源码: world_model_le.py LeWorldModel — forward(videos, actions):
    #   SigLIP 编码视频帧 + action_encoder 编码动作 → ARPredictor 预测下一帧
    #   与 DiT-B 并列 (训练时用真值动作), loss 按 lew_loss_weight 加权
    # === ✏️ 可修改区 END ===
    # 🔒 结构节点 (勿改)
    return (True, f"LEW: weight={lew_loss_weight}")


# ════════════════════════════════════════════════════════════════
# 🖼 DINOv2 视觉编码 — VLA-Touch visual_encoder (视觉嵌入条件)
# ════════════════════════════════════════════════════════════════
def node_dinov2(ctx):
    """🖼 DINOv2 视觉编码 — VLA-Touch 视觉条件 (dinov2-small 22M 冻结)"""
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    backbone = p.get("backbone", "dinov2-small")
    freeze = p.get("freeze", True)
    if log:
        log(f"🖼 DINOv2: {backbone} · freeze={freeze} (22M, 4060 无压力)")
    # 官方源码: residual_controller/visual_encoder.py DINOv2Encoder
    #   视觉嵌入 → Interpolant 控制器条件 (π_I(â|s,a,m) 的视觉通道)
    # === ✏️ 可修改区 END ===
    # 🔒 结构节点 (勿改)
    return (True, f"DINOv2: {backbone} freeze={freeze}")


# ════════════════════════════════════════════════════════════════
# 📍 Marker 触觉跟踪 — VLA-Touch marker_tracker (GelSight 标记位移→力)
# ════════════════════════════════════════════════════════════════
def node_marker(ctx):
    """📍 Marker 触觉跟踪 — GelSight 标记位移 → 低维力信号 m"""
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    grid = p.get("grid", "7x9")        # 标记网格 (GelSight 默认 7x9)
    dim = p.get("dim", 4)              # 输出力信号维度
    if log:
        log(f"📍 Marker: grid={grid} · dim={dim} (⚠️ metaworld 无真触觉, 当前状态差分模拟, 真机换 H06)")
    # 官方源码: residual_controller/tactile/marker/marker_tracker.py
    #   EnhancedMarkerTracker: 预处理→检测标记→位移→低维触觉信号 m_t
    # === ✏️ 可修改区 END ===
    # 🔒 结构节点 (勿改)
    return (True, f"Marker: {grid} dim={dim}")


# ════════════════════════════════════════════════════════════════
# 🌉 Interpolant 控制器 — VLA-Touch StochasticInterpolants (桥式扩散精炼)
# ════════════════════════════════════════════════════════════════
def node_interpolant(ctx):
    """🌉 Interpolant 控制器 — 触觉精炼 VLA 动作 (桥式扩散, 唯一训练模块)"""
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    diffuse_steps = p.get("diffuse_steps", 10)   # 采样扩散步数
    hidden = p.get("hidden", 256)                # 控制器隐藏宽度
    if log:
        log(f"🌉 Interpolant: diffuse_steps={diffuse_steps} · hidden={hidden}")
    # 官方源码: residual_controller/bridge/bridge_model.py StochasticInterpolants
    #   输入 x0=VLA 动作 / x1=专家动作 / cond=视觉+触觉+状态 → velocity_loss
    #   4060 精简: base VLA 冻结, 只训练此控制器 (≈1M 参数)
    # === ✏️ 可修改区 END ===
    # 🔒 结构节点 (勿改)
    return (True, f"Interpolant: steps={diffuse_steps} hidden={hidden}")


# ════════════════════════════════════════════════════════════════
# 🖐 SigLIP 视触觉编码 — AWE 场景原生 (视觉+力觉/触觉 原生融合)
# ════════════════════════════════════════════════════════════════
def node_siglip(ctx):
    """🖐 SigLIP 视触觉编码 — AWE 原生多模态 (视觉+力觉/触觉 场景级融合)"""
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    backbone = p.get("backbone", "siglip-base")
    freeze = p.get("freeze", True)
    tactile_dim = p.get("tactile_dim", 4)
    if log:
        log(f"🖐 SigLIP 视触觉: {backbone} · freeze={freeze} · tactile_dim={tactile_dim} (⚠️ metaworld 力觉为模拟)")
    # 官方源码: 对标它石 Born as One — 视觉·触觉·力觉·动作 从基因层面融合
    #   train_awe_zflow.py HJEPAEncoder: proj_vis + proj_state + proj_tactile 同层相加
    #   (非后期"乐高式"拼接)
    # === ✏️ 可修改区 END ===
    # 🔒 结构节点 (勿改)
    return (True, f"SigLIP 视触觉: {backbone} freeze={freeze}")


# ════════════════════════════════════════════════════════════════
# 🧠 H-JEPA 三层潜空间 — AWE zFlow (z₁空间/z₂物体/z₃语义)
# ════════════════════════════════════════════════════════════════
def node_hjepa(ctx):
    """🧠 H-JEPA 三层潜空间 — 空间/物体/语义 分层潜表示"""
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    d_z1 = p.get("d_z1", 128)    # z₁空间 (物体位姿)
    d_z2 = p.get("d_z2", 128)    # z₂物体 (类别属性)
    d_z3 = p.get("d_z3", 64)     # z₃语义 (任务目标)
    if log:
        log(f"🧠 H-JEPA: z₁={d_z1} z₂={d_z2} z₃={d_z3} (4060 等比缩小自 256/256/128)")
    # 官方源码: train_awe_zflow.py HJEPAEncoder — 三层潜空间头分离
    #   对标它石 OmniVTA / H-JEPA: 从被动感知 → 主动预测接触演化
    # === ✏️ 可修改区 END ===
    # 🔒 结构节点 (勿改)
    return (True, f"H-JEPA: z₁={d_z1} z₂={d_z2} z₃={d_z3}")


# ════════════════════════════════════════════════════════════════
# 🌊 zFlow 世界引擎 — AWE GRU 预测器 (潜空间推演未来状态)
# ════════════════════════════════════════════════════════════════
def node_zflow(ctx):
    """🌊 zFlow 世界引擎 — GRU 预测未来潜状态 (轻量, Orin Nano 可部署)"""
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    gru = p.get("gru", 128)      # GRU 隐藏宽度
    layers = p.get("layers", 1)
    if log:
        log(f"🌊 zFlow: GRU hidden={gru} · layers={layers}")
    # 官方源码: train_awe_zflow.py GRUPredictor — 潜状态+动作历史 → 未来潜状态
    #   对标它石 zFlow 世界引擎: 世界模型驱动后训练, 潜空间推演未来状态
    # === ✏️ 可修改区 END ===
    # 🔒 结构节点 (勿改)
    return (True, f"zFlow: GRU={gru}")


# ════════════════════════════════════════════════════════════════
# 🔀 未来决策交叉注意力 — AWE CrossAttnInject (预测潜状态 K/V 注入动作解码)
# ════════════════════════════════════════════════════════════════
def node_cross_attn(ctx):
    """🔀 未来决策交叉注意力 — 三层未来潜状态各作 K/V 注入动作解码 (真 CrossAttention, 分层门控 1.0/0.1/0.01)"""
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    gates = p.get("gates", "1.0/0.1/0.01")   # 三层潜状态门控权重 (z₁空间/z₂物体/z₃语义)
    if log:
        log(f"🔀 未来决策交叉注意力: gates={gates} (训练注入 / 推理门控归零可剥离, 零额外开销)")
    # 官方源码: train_awe_zflow.py CrossAttnInject (2026-08-05 老倪纠正为真 CrossAttention):
    #   z₁/z₂/z₃ 各自独立投影为 K/V token (ModuleList, 层间不共享) → Q=解码隐层
    #   → 逐层 MultiheadAttention 交互 → 每层输出乘各自门控再残差融合
    #   ⚠️ 不能拼接成单 token (那退化成恒等, 非真注意力)
    #   对标它石 LAS 隐空间丝滑动作 / OmniVTA 分层注入
    # === ✏️ 可修改区 END ===
    # 🔒 结构节点 (勿改)
    return (True, f"CrossAttn: gates={gates}")


# ════════════════════════════════════════════════════════════════
# ☑ 训练开关 — checkbox 打勾=训练 / 不打=不训练 (train_gate 节点)
# ════════════════════════════════════════════════════════════════
def node_train_gate(ctx):
    """☑ 训练开关 — 打勾=训练 / 不打=不训练 (放最前边控全链路)"""
    module = ctx["module"]
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    train_enabled = p.get("train_enabled", True)
    if log:
        log(f"☑ 训练开关: {'打勾 → 训练启用' if train_enabled else '不打勾 → 训练跳过'} (双击切换)")
    # 想自定义判定? 在这里写 (例如: 按时间段/产线状态自动决定是否训练)
    # === ✏️ 可修改区 END ===
    # 🔒 框架动作: 切换开关状态 (勿改)
    return module._toggle_train_gate_ctx(ctx["name"], train_enabled)


# ════════════════════════════════════════════════════════════════
# 🎯 YOLO 感知开关 — 有 YOLO(39D) / 无 YOLO(3D) (2026-08-06 老倪: state 输入 switch,
#    默认加载 YOLO 状态)
# ════════════════════════════════════════════════════════════════
def node_yolo_gate(ctx):
    """🎯 YOLO 感知开关 — 开=39D完整观测(YOLO检测产出) / 关=3D末端位置(无感知)"""
    module = ctx["module"]
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    yolo_enabled = p.get("yolo_enabled", True)  # 默认加载 YOLO (39D)
    state_dim = 39 if yolo_enabled else 3
    if log:
        log(f"🎯 YOLO 感知开关: {'开 → state 39D (YOLO检测产出, 含销钉/孔坐标)' if yolo_enabled else '关 → state 3D (仅末端位置, 无目标感知)'} · 默认开")
    # 想自定义判定? 在这里写 (例如: 按相机可用性自动切换)
    # === ✏️ 可修改区 END ===
    # 🔒 框架动作: 记录开关状态到节点 (勿改)
    return module._set_yolo_gate_ctx(ctx["name"], yolo_enabled, state_dim)


# ════════════════════════════════════════════════════════════════
# 🎥 视频显示 — 推理效果对比 (rollout 视频播放窗口)
# ════════════════════════════════════════════════════════════════
def node_video_display(ctx):
    """🎥 视频显示 — 训练后 rollout 推理效果 (多窗口同步播放)"""
    module = ctx["module"]
    log = ctx["log"]
    # === ✏️ 可修改区 START ===
    if log:
        log("🎥 视频显示: 双击 → 多模型 rollout 视频同步播放对比 (推理效果)")
    # 想自定义? 例如: 只播放指定模型的视频
    # === ✏️ 可修改区 END ===
    # 🔒 框架动作: 推理效果对比 (勿改)
    return module.on_infer_video()


# ════════════════════════════════════════════════════════════════
# 📄 PDF 技术选型报告 — 五模型对比实验 → 11 章专业报告
# ════════════════════════════════════════════════════════════════
def node_pdf_report(ctx):
    """📄 PDF 技术选型报告 — 概况/系统全貌/分系统功能/接口/参数/架构/功能/性价比/优劣势"""
    module = ctx["module"]
    log = ctx["log"]
    if log:
        log("📄 生成五模型对比技术选型报告 (数据: 曲线+视频+画布拓扑)")
    # === ✏️ 可修改区 END ===
    return module.on_pdf_report()


# ── 🔒 框架区: 注册表 (勿改) ──────────────────────────────────────
_reg("collect",    ["采集"],        "① 采集 — 拉取 Orin 真实数据 → 修复 action → 落地", node_collect)
_reg("train",      ["训练", "全新训练"], "② 训练 — ACT 策略训练 (含 metaworld 全新训练)", node_train)
_reg("validate",   ["验证"],        "③ 验证 — 流程拓扑合规检查 (validate_flow)", node_validate)
_reg("integrate",  ["集成"],        "④ 集成 — 打包 checkpoint → 上传 ECS 中转", node_integrate)
_reg("deploy",     ["部署"],        "⑤ 部署 — 部署状态检查与推送", node_deploy)
_reg("infer",      ["推理"],        "⑥ 推理 — 产线推理服务状态", node_infer)
_reg("mode_switch", ["训练/推理", "模式开关"], "🔀 训练/推理模式开关 — 双击切换 train⇄infer", node_mode_switch)
_reg("infer_rollout", ["推理 (rollout)", "rollout"], "📷 推理 (rollout) — 最新模型仿真插拔评估+视频", node_infer_rollout)
_reg("eval_state_space", ["模型评估 (状态空间)", "状态空间评估"], "📊 状态空间稳定性评估 — L2/BIBO/谱半径/状态机覆盖", node_eval_state_space)
_reg("spectral_norm", ["谱归一化"], "🧮 谱归一化 — 左脑逐层 σ_max → Lipschitz 上界", node_spectral_norm)
_reg("gru_gate", ["GRU 门控"], "🧮 GRU 门控机制 — 右脑潜空间 ρ(W) 收缩", node_gru_gate)
_reg("force_limit", ["力幅值限幅"], "🧮 力幅值限幅 — 插入阶段饱和 → 临界阻尼 ζ", node_force_limit)
_reg("eval_report_pdf", ["稳定性评估 PDF"], "📄 稳定性评估汇总 PDF — 公式+图+数据+结论 → 飞书", node_eval_report_pdf)
_reg("ff_pd_control", ["前馈 PD"], "⚙️ 前馈 PD 控制器 — 顶层增益调度PID+前馈, Z700=底层", node_ff_pd_control)
_reg("ff_ref_input", ["参考输入"], "📡 参考输入 u(t) — 前馈PD顶层输入", node_ff_ref_input)
_reg("ff_scope", ["输出 Scope"], "🖥 输出 Scope — 前馈PD顶层输出响应", node_ff_scope)
_reg("z700_internal", ["Z700 内部"], "🔬 Z700 内部模块 (顶层只读展示)", node_z700_internal)
_reg("data",       ["metaworld 数据", "metaworld数据"], "📦 数据源选择", node_metaworld_data)
_reg("resnet18",   ["ResNet18", "resnet18"], "🖼 视觉主干 — ACT.backbone", node_resnet18)
_reg("cvae",       ["CVAE", "cvae"], "🧬 VAE 编码器 — 动作条件变分自编码器", node_cvae)
_reg("encoder",    ["Encoder", "encoder"], "🔤 Transformer Encoder — 上下文向量", node_encoder)
_reg("decoder",    ["Decoder", "decoder"], "🔡 Transformer Decoder — 动作序列", node_decoder)
_reg("action_head", ["Action Head", "action_head"], "🎯 Action Head — 关节动作映射", node_action_head)
_reg("ensemble",   ["Temporal Ensemble", "Ensemble"], "⏳ Temporal Ensemble — 动作平滑", node_ensemble)
_reg("scope",      ["Scope"], "📊 Scope 示波器 — 训练效果波形", node_scope)
# 🆕 2026-08-08 老倪: 总系统节点标准化 — Subsystem 双击展开「🔬 模型对比」
def node_topsys(module, node, label=None):
    """🔬 总系统 (Subsystem) — 双击展开「🔬 模型对比」七模型训练线"""
    try:
        sub = (node.get("params") or {}).get("subsystem", "🔬 模型对比")
        if getattr(module, "load_reference_app_by_name", None):
            module.load_reference_app_by_name(sub)
            module._log(f"🔬 总系统 → 展开子系统: {sub}")
    except Exception:
        pass
    return None, "总系统子系统"

_reg("topsys",     ["总系统", "Subsystem"], "🔬 总系统 — Subsystem 双击展开模型对比", node_topsys)
# 🆕 2026-08-05 新增模型节点 (五模型对比 / VLA-Touch / AWE 管道)
_reg("smolvlm2",   ["SmolVLM2"], "🧠 SmolVLM2-500M — 视觉语言主干", node_smolvlm2)
_reg("dit_b",      ["DiT-B", "DiT"], "🌀 DiT-B 动作解码 — 扩散动作生成器", node_dit_b)
_reg("lew",        ["LeWorldModel"], "🌐 LeWorldModel — 潜空间世界模型", node_lew)
_reg("dinov2",     ["DINOv2"], "🖼 DINOv2 视觉编码 — VLA-Touch 视觉条件", node_dinov2)
_reg("marker",     ["Marker"], "📍 Marker 触觉跟踪 — GelSight 标记位移→力", node_marker)
_reg("interpolant", ["Interpolant"], "🌉 Interpolant 控制器 — 桥式扩散精炼", node_interpolant)
_reg("siglip",     ["SigLIP"], "🖐 SigLIP 视触觉编码 — AWE 原生多模态融合", node_siglip)
_reg("hjepa",      ["H-JEPA"], "🧠 H-JEPA 三层潜空间 — z₁/z₂/z₃ 分层潜表示", node_hjepa)
_reg("zflow",      ["zFlow"], "🌊 zFlow 世界引擎 — GRU 预测未来潜状态", node_zflow)
_reg("cross_attn", ["交叉注意力"], "🔀 未来决策交叉注意力 — 未来潜状态 K/V 注入", node_cross_attn)
_reg("train_gate", ["训练开关"], "☑ 训练开关 — 打勾=训练 / 不打=不训练", node_train_gate)
_reg("yolo_gate", ["YOLO开关"], "🎯 YOLO 感知开关 — 开=39D(有YOLO) / 关=3D(无YOLO), 默认开", node_yolo_gate)


# ── 🎯 YOLO 3D 感知链 (2026-08-12 老倪: 源码显示 yolo_3d/, 右键菜单也可打开) ──
def node_yolo_3d(ctx):
    log = ctx["log"]
    """🎯 YOLO 3D — 相机图像 → 检测销钉/插孔/末端 (mAP 0.994) → 2D→3D 解算 → 39D state
    真实实现: src/lerobot/policies/yolo_3d/ (train_yolo / yolo_state_aligner / gen_yolo_data / gen_tactile)
    ─────────────────────────────────────────────
    📂 YOLO 模型加载位置:
      · 加载代码: yolo_state_aligner.py:37 __init__ → YOLO(weights) (ultralytics)
      · 调用入口: tools/gen_metaworld_data.py:41 WEIGHTS 常量 + :48 YoloStateAligner(WEIGHTS, env)
      · 加载时机: 运行数据生成脚本时加载一次, detect_3d() 每帧只推理不重载
    💾 权重文件: runs/detect/outputs/yolo_peg/peg_full/weights/best.pt (22MB, 8/07 训练)
    ─────────────────────────────────────────────
    数据流: YOLO 检测 {hand, peg, hole} → 反投影 3D → 替换 39D 中 hand[0:3]/peg[18:21]/hole[36:39]"""
    p = ctx.get("params", {})
    log(f"🎯 YOLO 3D: model={p.get('model','yolov8s')} classes={p.get('classes','peg/hole/hand')} · mAP 0.994 · 权重 runs/detect/outputs/yolo_peg/peg_full/weights/best.pt")
    return True


def node_yolo_align(ctx):
    log = ctx["log"]
    """📐 2D→3D 解算 — YOLO 2D 框中心 + 相机内参 → 目标 3D 坐标 (pixel_to_ray / ray_plane_intersect / YoloStateAligner)"""
    p = ctx.get("params", {})
    log(f"📐 2D→3D 解算: intrinsics={p.get('intrinsics','camera_K')} method={p.get('method','depth|hand-eye')} · 源码 yolo_state_aligner.py")
    return True


def node_yolo_tactile(ctx):
    log = ctx["log"]
    """📍 Marker 触觉跟踪 — GelSight 标记位移 → 4D 触觉力信号 (夹持/接触/滑觉); 数据改造: metaworld_peg → 43D"""
    p = ctx.get("params", {})
    log(f"📍 Marker 触觉跟踪: grid={p.get('grid','7x9')} dim={p.get('dim',4)} · 触觉数据生成 gen_tactile.py")
    return True


_reg("yolo_3d",     ["YOLO 3D"], "🎯 YOLO 3D — 检测销钉/插孔/末端 → 2D→3D → 39D state (源码 yolo_3d/)", node_yolo_3d)
_reg("yolo_align",  ["2D→3D"], "📐 2D→3D 解算 — 像素→3D 坐标 (源码 yolo_3d/yolo_state_aligner.py)", node_yolo_align)
_reg("yolo_tactile", ["Marker 触觉"], "📍 Marker 触觉跟踪 — 4D 触觉信号 (源码 yolo_3d/gen_tactile.py)", node_yolo_tactile)


# ── 📦 Z700 数据源 / 适配 / obs (2026-08-12 老倪: 每个节点都有代码) ──
def node_metaworld_peg(ctx):
    log = ctx["log"]
    """📦 metaworld_peg — 仿真插拔数据集 (39D 状态 + 图像, 24集 4800帧)
    数据生成: tools/gen_metaworld_data.py; 触觉增强: src/lerobot/policies/yolo_3d/gen_tactile.py (39D→43D)"""
    p = ctx.get("params", {})
    log(f"📦 metaworld_peg: frames={p.get('frames', 4800)} dims={p.get('dims', '4D/4D')} · 数据源: 喂感知链+训练")
    return True


def node_state_adapter(ctx):
    log = ctx["log"]
    """🔌 State Adapter — 感知融合: 视觉 39D + 触觉 4D = 43D 统一输入
    数据流适配: 归一化/拼接/维度对齐 (策略输入接口, 与训练配置 processor 对应)"""
    p = ctx.get("params", {})
    log(f"🔌 State Adapter: in={p.get('in_dim', 43)} out={p.get('out_dim', 43)} normalize={p.get('normalize', True)} · 视觉39D+触觉4D=43D")
    return True


def node_obs43(ctx):
    log = ctx["log"]
    """📊 43D obs 输入 — 感知链与策略的统一状态输入 (39D 视觉/关节 + 触觉 4D)

    结构: 43D = 当前帧(18) + 上一帧(18) + 目标(3) + 触觉(4)   [双帧堆叠 + Marker 触觉]
    ─────────────────────────────────────────────
    39D 部分 (metaworld peg-insertion 观测, 与 node_obs39 一致):
    [0:3]    hand_pos      末端执行器位置 xyz    单位: 米(m)
    [3]      gripper       夹爪开度 (归一化)     0=闭合 · 1=张开
    [4:7]    peg_pos       销钉位置 xyz          单位: 米(m)
    [7:11]   peg_quat      销钉姿态四元数 xyzw   单位四元数 (w=1 无旋转)
    [11:18]  pad           填充槽 ×7 (固定 0)    物体槽位余量
    [18:21]  prev_hand_pos 上一帧末端位置 xyz    单位: 米(m)
    [21]     prev_gripper  上一帧夹爪开度        0=闭合 · 1=张开
    [22:25]  prev_peg_pos  上一帧销钉位置 xyz    单位: 米(m)
    [25:29]  prev_peg_quat 上一帧销钉四元数 xyzw 单位四元数
    [29:36]  prev_pad      填充槽 ×7 (固定 0)
    [36:39]  hole_pos      插孔目标位置 xyz      单位: 米(m) (goal)
    ─────────────────────────────────────────────
    触觉 4D (Marker 触觉跟踪, gen_tactile.py 从 39D state 合成):
    [39]     grasp_force   夹持力   = 1 − gripper   (夹爪闭合=1, 张开=0)
    [40]     contact_force 接触力   = 1/(1+5d)      (d=|peg−hole|, 越近越大)
    [41]     contact_dir_x 接触方向x = (peg_x−hole_x)/d
    [42]     contact_dir_z 接触方向z = (peg_z−hole_z)/d
    ─────────────────────────────────────────────
    说明: 视觉/关节 39D 双帧堆叠感知时序, 触觉 4D 补力觉通道 (metaworld 无 GelSight 真实触觉)"""
    p = ctx.get("params", {})
    log(f"📊 43D obs: dims={p.get('dims', 43)} · 39D 结构(双帧堆叠+目标) + 触觉4D")
    return True


def node_solution_web(ctx):
    log = ctx["log"]
    """🌐 方案介绍 — 打开方案介绍分页 (datadrive.world/solution.html, 含PDF下载)
    网页: zmax-website/solution.html + Z700-方案介绍.pdf (线上部署)"""
    p = ctx.get("params", {})
    log("🌐 方案介绍: 打开 https://datadrive.world/solution.html · 光模块工厂5大场景/架构/节点职责")
    return True


_reg("metaworld_peg", ["metaworld_peg"], "📦 metaworld_peg — 插拔数据集 39D+图像 (源码 tools/gen_metaworld_data.py)", node_metaworld_peg)
_reg("state_adapter", ["State Adapter"], "🔌 State Adapter — 视觉39D+触觉4D=43D 融合适配", node_state_adapter)
_reg("obs43", ["43D obs"], "📊 43D obs 输入 — 39D结构+触觉4D=43D 统一输入", node_obs43)
_reg("solution_web", ["方案介绍"], "🌐 方案介绍 — 打开方案分页 (datadrive.world/solution.html)", node_solution_web)


# ── ➤ 状态机 6 阶段 (2026-08-12 老倪: 每阶段代码, 参数对应 configuration_left_right.py) ──
def node_stage_approach(ctx):
    log = ctx["log"]
    p = ctx.get("params", {})
    log(f"➤ 接近: bias={p.get('bias', 'act*0.3 + hand→peg方向*2.0')} · 规则方向+学习修正 (5/8 vs 0/8)")
    return True


def node_stage_grasp(ctx):
    log = ctx["log"]
    p = ctx.get("params", {})
    log(f"➤ 抓取: effort={p.get('effort', 0.6)} · 专家式夹持+位置锁定")
    return True


def node_stage_lift(ctx):
    log = ctx["log"]
    p = ctx.get("params", {})
    log(f"➤ 抬起: height={p.get('height', 0.08)}m force={p.get('force', 0.8)} · 避开台面")
    return True


def node_stage_transfer(ctx):
    log = ctx["log"]
    p = ctx.get("params", {})
    log(f"➤ 转移: tolerance={p.get('tolerance', 0.05)}m · peg 有导向")
    return True


def node_stage_insert(ctx):
    log = ctx["log"]
    p = ctx.get("params", {})
    log(f"➤ 插入: tolerance={p.get('tolerance', 0.05)}m · 完成插拔")
    return True


def node_stage_done(ctx):
    log = ctx["log"]
    p = ctx.get("params", {})
    log(f"➤ 完成: stage={p.get('stage', 'done')} · 释放/复位, 进入下一循环")
    return True


_reg("stage_approach", ["➤ 接近"], "➤ 接近 — 偏置接近 (状态机第1阶段, 源码 left_right/)", node_stage_approach)
_reg("stage_grasp",    ["➤ 抓取"], "➤ 抓取 — 专家式夹持 0.6 (状态机第2阶段)", node_stage_grasp)
_reg("stage_lift",     ["➤ 抬起"], "➤ 抬起 — +8cm 避台面 (状态机第3阶段)", node_stage_lift)
_reg("stage_transfer", ["➤ 转移"], "➤ 转移 — 容差 5cm (状态机第4阶段)", node_stage_transfer)
_reg("stage_insert",   ["➤ 插入"], "➤ 插入 — 完成插拔 (状态机第5阶段)", node_stage_insert)
_reg("stage_done",     ["➤ 完成"], "➤ 完成 — 释放复位 (状态机第6阶段)", node_stage_done)


# ════════════════════════════════════════════════════════════════
# 🧩 坐标叠加 (CoordOverlay) — 2026-08-08 老倪架构: 坐标是逻辑主线,
#    图像是背景 — state 叠加进 latent (latent += 坐标投影), 不混合进 token 序列
# ════════════════════════════════════════════════════════════════
def node_coord_overlay(ctx):
    """🧩 坐标叠加 — 坐标投影叠加到 latent (逻辑主线), 图像作背景 token (旁路)"""
    module = ctx["module"]
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    gate = p.get("overlay_gate", 1.0)      # 叠加门控: 1.0=坐标完全叠加, 0.0=禁用叠加
    state_dim = p.get("state_dim", 45)     # 39D 或 45D (含相对向量)
    if log:
        log(f"🧩 坐标叠加: latent += 坐标投影 × {gate} (state {state_dim}D) — 图像降为背景 token, 坐标是逻辑主线")
    # 想自定义? 例如: 按任务切换 gate 或 state_dim
    # === ✏️ 可修改区 END ===
    # 🔒 框架动作: 记录叠加状态到节点 (勿改)
    fn = getattr(module, "_set_coord_overlay_ctx", None)
    return fn(ctx["name"], gate, state_dim) if fn else None


_reg("coord_overlay", ["结构条件", "坐标叠加", "CoordOverlay"], "🧩 结构条件 — state 叠加进 latent (逻辑主线), 图像作背景", node_coord_overlay)
_reg("video_display", ["视频"], "🎥 视频显示 — 推理效果 rollout 播放", node_video_display)
_reg("pdf_report",   ["PDF"], "📄 PDF 报告 — 五模型技术选型 (11章)", node_pdf_report)


# ════════════════════════════════════════════════════════════════
# 🧠 left_right 双脑工程 (2026-08-10 老倪: 左脑MLP动作 + 右脑WM判断 + 状态机)
#   真实实现: src/lerobot/policies/left_right/modeling_left_right.py
#   位置映射: _EXTERNAL_LOC (VSCode 打开真实源码)
# ════════════════════════════════════════════════════════════════
# 📂 外部源码位置: 语义key → (绝对路径, 行号, 真实符号名) — 覆盖 node_logic.py 自身位置
_EXTERNAL_LOC = {}
# node_logic.py 在 <root>/tools/gui/ → 仓库根 = dirname ×3
_LR_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(_LOGIC_FILE))), "src", "lerobot", "policies", "left_right")
_EXTERNAL_LOC["left_brain"]  = (os.path.join(_LR_DIR, "modeling_left_right.py"), 44, "class LeftBrainMLP")   # 🐛 2026-08-10: 显示真实符号名, 不是 node_logic 函数名
_EXTERNAL_LOC["right_brain"] = (os.path.join(_LR_DIR, "modeling_left_right.py"), 59, "class RightBrainWM")
_EXTERNAL_LOC["left_right"]  = (os.path.join(_LR_DIR, "modeling_left_right.py"), 75, "class LeftRightPolicy")
_EXTERNAL_LOC["lr_contact"]  = (os.path.join(_LR_DIR, "configuration_left_right.py"), 34, "class LeftRightConfig")  # 🐛 2026-08-12: 原 sym 非符号名定位失败 → 显示整个配置类 (含接触/状态机阈值)

# 🎯 YOLO 3D 感知链 (2026-08-12 老倪: 查看/编辑节点逻辑 → 显示真实源码 yolo_3d/)
_YOLO_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(_LOGIC_FILE))), "src", "lerobot", "policies", "yolo_3d")
_EXTERNAL_LOC["yolo_3d"] = (os.path.join(_YOLO_DIR, "yolo_state_aligner.py"), 37, "class YoloStateAligner")   # 🎯 YOLO 3D 检测+2D→3D 核心
_EXTERNAL_LOC["yolo_align"] = (os.path.join(_YOLO_DIR, "yolo_state_aligner.py"), 11, "def pixel_to_ray")  # 📐 2D→3D 解算: 像素→射线→平面交点 (反投影实现, 非整个类)
_EXTERNAL_LOC["yolo_tactile"] = (os.path.join(_YOLO_DIR, "gen_tactile.py"), 1, "gen_tactile")                  # 📍 Marker 触觉跟踪 (触觉数据生成)
# 🐛 2026-08-12: state_adapter 不挂外部源码 — 原误指 yolo_state_aligner.py (与 YOLO 3D 相同, 用户指出);
#   State Adapter 是融合节点 (视觉39D+触觉4D=43D), 无独立实现 → 显示 node_state_adapter 自身函数 (可编辑区)
# 注: obs39 不注册外部映射 — 用户要的是结构说明 (node_obs39 函数体), 不是 metaworld 内部源码


def node_obs39(ctx):
    """📊 39D obs 输入 — metaworld peg-insertion 完整观测 (2026-08-10 实测确认)

    结构: 39D = 当前帧(18) + 上一帧(18) + 目标(3)   [帧堆叠]
    ─────────────────────────────────────────────
    [0:3]    hand_pos      末端执行器位置 xyz    单位: 米(m)
    [3]      gripper       夹爪开度 (归一化)     0=闭合 · 1=张开
    [4:7]    peg_pos       销钉位置 xyz          单位: 米(m)
    [7:11]   peg_quat      销钉姿态四元数 xyzw   单位四元数 (w=1 无旋转)
    [11:18]  pad           填充槽 (固定 0)       物体槽位余量
    [18:21]  prev_hand_pos 上一帧末端位置 xyz    单位: 米(m)
    [21]     prev_gripper  上一帧夹爪开度        0=闭合 · 1=张开
    [22:25]  prev_peg_pos  上一帧销钉位置 xyz    单位: 米(m)
    [25:29]  prev_peg_quat 上一帧销钉四元数 xyzw 单位四元数
    [29:36]  prev_pad      填充槽 (固定 0)
    [36:39]  hole_pos      插孔目标位置 xyz      单位: 米(m) (goal)
    ─────────────────────────────────────────────
    说明: peg-insertion 观测 = 末端+夹爪+销钉(位姿) 双帧堆叠 + 目标孔位。
    45D 版本 = 39D + 6D 相对向量 (peg-hand, hole-peg); 49D 加触觉; 58D 加 W2-CoT。
    left_right 工程用 39D (无相对向量)。
    """
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    dim = p.get("dim", 39)
    if log:
        log(f"📊 39D obs: 末端{3}+夹爪{1}+销钉{7} ×2帧 + 孔位{3} = 39D (帧堆叠, 单位 m/四元数)")
    # === ✏️ 可修改区 END ===
    return True


def node_left_brain(ctx):
    """🧠 左脑 LeftBrainMLP — 39D obs → 4D 连续动作 (动作生成, 547K)"""
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    hidden = p.get("hidden", 512)
    if log:
        log(f"🧠 左脑 LeftBrainMLP: 39D obs → 4D 动作 · 隐藏 {hidden} · 547K 参数 (MLP偏置接近 act*0.3+delta*2.0)")
    # === ✏️ 可修改区 END ===
    return True


def node_right_brain(ctx):
    """🧠 右脑 RightBrainWM — obs+action → next obs + contact 概率 (抓取时机, 87K, acc 1.00)"""
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    hidden = p.get("hidden", 256)
    if log:
        log(f"🧠 右脑 RightBrainWM: obs+action → next obs + contact 概率 · 隐藏 {hidden} · 87K (contact>0.5 & d_hp<0.06 → 抓)")
    # === ✏️ 可修改区 END ===
    return True


def node_left_right_policy(ctx):
    """◉ LeftRightPolicy — lerobot 标准封装: 左脑动作 + 右脑判断 + 状态机编排 (抓起8/8 插入7/8)"""
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    th = p.get("grasp_contact_threshold", 0.5)
    dhp = p.get("grasp_d_hp", 0.06)
    lift = p.get("lift_height", 0.08)
    if log:
        log(f"◉ LeftRightPolicy: 状态机 接近→抓取(contact>{th} & d_hp<{dhp})→抬起(+{lift}m)→转移→插入 → 完成 · 125帧")
    # === ✏️ 可修改区 END ===
    return True


def node_lr_contact(ctx):
    """❖ 接触判定 — 右脑 contact 概率 + 钳口-销钉距离 联合判定 → 夹持触发"""
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    th = p.get("contact_th", 0.5)
    dhp = p.get("d_hp_th", 0.06)
    if log:
        log(f"❖ 接触判定: contact>{th} & d_hp<{dhp} → 夹持触发 (右脑 get_right_contact)")
    # === ✏️ 可修改区 END ===
    return True


_reg("left_brain",  ["LeftBrainMLP"], "🧠 左脑 LeftBrainMLP — 39D→4D 连续动作 (547K, 源码 modeling_left_right.py:44)", node_left_brain)
_reg("right_brain", ["RightBrainWM"], "🧠 右脑 RightBrainWM — contact 时机判断 (87K, 源码 modeling_left_right.py:59)", node_right_brain)
_reg("left_right",  ["LeftRightPolicy"], "◉ LeftRightPolicy — 双脑+状态机 lerobot 封装 (源码 modeling_left_right.py:75)", node_left_right_policy)
_reg("lr_contact",  ["接触判定"], "❖ 接触判定 — contact 阈值 + 距离联合判定 (参数在 configuration_left_right.py:44)", node_lr_contact)
_reg("obs39",       ["39D obs", "39D"], "📊 39D obs 输入 — metaworld 完整观测结构 (末端/夹爪/销钉×2帧+孔位, 含单位与解释)", node_obs39)

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
    fn = info["fn"]
    modified = key in _SOURCE_CACHE
    path = getattr(fn.__code__, "co_filename", None)
    line = getattr(fn.__code__, "co_firstlineno", None)
    if not path or not path.endswith(".py"):
        path = _LOGIC_FILE
        line = None
    return path, line, modified


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
    """② 训练 — ACT 策略训练 (参数在可修改区, 真实写入训练配置)"""
    module = ctx["module"]
    log = ctx["log"]
    p = ctx["params"]
    # === ✏️ 可修改区 START ===
    steps = p.get("steps", 300)      # 训练步数 (4060 实测 ~13步/s, 300步≈40s)
    batch_size = 8                   # batch size
    lr = 1e-4                        # 学习率 (S3 真机微调用 1e-5)
    data_source = "auto"             # auto(画布switch决定) | orin(只拉真实) | metaworld(占位集)
    if log:
        log(f"🧠 训练配置: steps={steps} · batch={batch_size} · lr={lr} · 数据源={data_source}")
    # 想改训练逻辑? 在这里写 (例如: 按数据帧数自动调整 steps)
    # === ✏️ 可修改区 END ===
    # 🔒 框架动作: 真实 lerobot_train (数据源智能选择, 勿改)
    return module.on_train(steps=steps, batch_size=batch_size, lr=lr, data_source=data_source)


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
    use_vae = p.get("use_vae", True)       # 是否启用 VAE (False=确定性策略)
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


# ── 🔒 框架区: 注册表 (勿改) ──────────────────────────────────────
_reg("collect",    ["采集"],        "① 采集 — 拉取 Orin 真实数据 → 修复 action → 落地", node_collect)
_reg("train",      ["训练", "全新训练"], "② 训练 — ACT 策略训练 (含 metaworld 全新训练)", node_train)
_reg("validate",   ["验证"],        "③ 验证 — 流程拓扑合规检查 (validate_flow)", node_validate)
_reg("integrate",  ["集成"],        "④ 集成 — 打包 checkpoint → 上传 ECS 中转", node_integrate)
_reg("deploy",     ["部署"],        "⑤ 部署 — 部署状态检查与推送", node_deploy)
_reg("infer",      ["推理"],        "⑥ 推理 — 产线推理服务状态", node_infer)
_reg("data",       ["metaworld 数据", "metaworld数据"], "📦 数据源选择", node_metaworld_data)
_reg("resnet18",   ["ResNet18", "resnet18"], "🖼 视觉主干 — ACT.backbone", node_resnet18)
_reg("cvae",       ["CVAE", "cvae"], "🧬 VAE 编码器 — 动作条件变分自编码器", node_cvae)
_reg("encoder",    ["Encoder", "encoder"], "🔤 Transformer Encoder — 上下文向量", node_encoder)
_reg("decoder",    ["Decoder", "decoder"], "🔡 Transformer Decoder — 动作序列", node_decoder)
_reg("action_head", ["Action Head", "action_head"], "🎯 Action Head — 关节动作映射", node_action_head)
_reg("ensemble",   ["Temporal Ensemble", "Ensemble"], "⏳ Temporal Ensemble — 动作平滑", node_ensemble)
_reg("scope",      ["Scope"], "📊 Scope 示波器 — 训练效果波形", node_scope)

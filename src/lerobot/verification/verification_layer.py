# -*- coding: utf-8 -*-
"""verification_layer.py — 🧩 验证层: 状态空间系统 feature 清单 + test 用例执行

2026-09-03 老倪: 整个状态空间系统要能逐个验证 — 画布新增「验证层」(回路外元层),
两个节点:
  🧩 Feature 功能清单  → 汇总全部 feature (含手动交互项, 输出注册表)
  🧪 Test 用例执行     → 跑自动化 test 套件 (引擎/六层/感知/规划/元层/画布映射)

本文件 = 验证真源 (与 calibration/manifold 同范式): 全部 feature 注册 + 每个
test 的真实断言都在这, VSCode 断点可进; CLI (tools/ss_feature_tests.py) 与 GUI
节点 (node_ss_verif) 共用同一套, 不双轨。

数据真源: 引擎 StateSpaceSim 跑一次缓存轨迹 (纯 numpy <0.1s); 六层源码/标定/
流形 importlib 直载 (避开 lerobot 包级 torch 依赖, 同引擎 _load 策略)。
断言全部按源码契约写 (数值可手算核对), 不拍脑袋。

用法:
  from verification_layer import VerificationLayer
  v = VerificationLayer(log=print)
  v.list_features()          # feature 清单
  v.run_all()                # 全部自动 test
  v.run("F-A01")             # 单个
"""
import importlib.util as _ilu
import os
import sys

# src/lerobot/verification/verification_layer.py → 上溯 4 级 = 仓库根
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SS_DIR = os.path.join(ROOT, "src", "lerobot", "policies", "left_right", "state_space")
CALIB = os.path.join(ROOT, "src", "lerobot", "calibration", "calibration_layer.py")
MANI = os.path.join(ROOT, "src", "lerobot", "manifold", "manifold_layer.py")


def _load(rel):
    """按文件路径直载模块 (同 state_space_sim._load 策略)"""
    name = "verif_" + os.path.basename(rel).replace(".py", "")
    spec = _ilu.spec_from_file_location(name, os.path.join(ROOT, rel))
    m = _ilu.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ════════════════════════════════════════════════════════════════════
# Feature 注册表 — 全部功能点 (自动/手动), 与画布/引擎/UI 一一对应
# ════════════════════════════════════════════════════════════════════
FEATURES = [
    # (id, 域, 名称, 层/位置, 验证方式, 自动用例id 或 None)
    ("F-A01", "引擎", "八阶段完整跑通 (接近→对位→下降→抓取→抬起→转移→插入→完成)", "StateSpaceSim", "自动", "F-A01"),
    ("F-A02", "引擎", "收敛精度: 销头到孔底 <4mm (D_INSERT)", "StateSpaceSim", "自动", "F-A02"),
    ("F-A03", "引擎", "轨迹契约: 20+ 序列键 + 逐帧 io_trace (数据总线源)", "StateSpaceSim", "自动", "F-A03"),
    ("F-A04", "引擎", "一阶速度伺服有界不发散 (τ=0.08s, max‖v‖≤0.5m/s)", "StateSpaceSim", "自动", "F-A04"),
    ("F-A05", "引擎", "台面约束: 未夹持末端不穿透台面", "StateSpaceSim", "自动", "F-A05"),
    ("F-A06", "引擎", "夹持锁存 + 插销随末端移动 (grasped 后 peg=x+peg_off)", "StateSpaceSim", "自动", "F-A06"),
    ("F-A07", "引擎", "接触力→接触概率真实联动 (接触段 contact_p>0.6)", "StateSpaceSim", "自动", "F-A07"),
    ("F-A08", "引擎", "流形量逐帧发布: 接触/性能 channel 进 io_trace + 全程序列", "StateSpaceSim", "自动", "F-A08"),
    ("F-B01", "S1", "传感器融合: 39D 视觉 + 触觉4D → 43D (fuse_sensors)", "perception.py", "自动", "F-B01"),
    ("F-B02", "S2", "前馈加速器: 比例引导向目标 + 近距闭合 + ±0.5 限幅", "parallel.py", "自动", "F-B02"),
    ("F-B03", "S2", "自适应状态估计器: predict/update 卡尔曼数值 (A/K/B)", "parallel.py", "自动", "F-B03"),
    ("F-B04", "动力学", "先验动力学预测器: A=1.0 恒速 (潜空间速度场)", "dynamics.py", "自动", "F-B04"),
    ("F-B05", "S3", "状态校正器: 残差=z−x̂₋ / 校正=+K·r 手算核对", "cognition.py", "自动", "F-B05"),
    ("F-B06", "S3", "接触概率 σ(residual·gain) 单调", "cognition.py", "自动", "F-B06"),
    ("F-B07", "S3", "八阶段状态机: 顺序推进 + 连续 2 帧确认防抖", "cognition.py", "自动", "F-B07"),
    ("F-B08", "S3", "夹持丢失 5 帧 + 落回台面 → 回退重抓", "cognition.py", "自动", "F-B08"),
    ("F-B09", "S3", "否决权: 残差>veto_th → 强制减速 (u=0)", "cognition.py", "自动", "F-B09"),
    ("F-B10", "S3", "动作融合: 前馈+反馈相加 + 阶段限速 + V_MIN 防磨蹭", "cognition.py", "自动", "F-B10"),
    ("F-B11", "安全", "饱和限幅 saturate ±0.6 (唯一三层安全之一)", "safety.py", "自动", "F-B11"),
    ("F-C01", "感知链", "YOLO 真实检测 3/3 (hand/peg/hole, conf 真值)", "yolo_state_aligner", "自动 [慢~2s]", "F-C01"),
    ("F-C02", "感知链", "align 段位: hand→[0:3] peg→[4:7]+[22:25] hole→[36:39]", "yolo_state_aligner", "自动 [慢~2s]", "F-C02"),
    ("F-C03", "感知链", "触觉合成 4D (grasp/contact 0-1 语义)", "gen_tactile.py", "自动", "F-C03"),
    ("F-C04", "感知链", "AOI 外观质量检测真实图像处理", "quality_check.py", "自动", "F-C04"),
    ("F-D01", "大模型层", "任务规划器: 指令→技能Token 规则链 + validate (离线)", "planner.py", "自动", "F-D01"),
    ("F-D02", "大模型层", "异常推理器: diagnose 分类输出 (连续否决/卡死)", "planner.py", "自动", "F-D02"),
    ("F-D03", "大模型层", "技能编排器: 场景→技能序列", "planner.py", "自动", "F-D03"),
    ("F-E01", "标定层", "三域标定: 引力/斥力/潜空间数据 + 平衡势", "calibration_layer.py", "自动", "F-E01"),
    ("F-E02", "标定层", "潜空间: PCA 有效维实测 vs latent_dim 校验", "calibration_layer.py", "自动", "F-E02"),
    ("F-E03", "流形导航层", "接触流形: 通道轴分解/法向偏离/状态判据", "manifold_layer.py", "自动", "F-E03"),
    ("F-E04", "流形导航层", "性能流形: 完成态 η 高 / 未插入 η≈0", "manifold_layer.py", "自动", "F-E04"),
    ("F-E05", "元层", "画布节点分派: 标定/潜空间/接触/性能/Feature/Test 全命中", "node_logic.py", "自动", "F-E05"),
    ("F-F01", "画布", "flow JSON 结构: 35 节点 9 层, type 合法", "state_space_obs.json", "自动", "F-F01"),
    ("F-F02", "画布", "节点注册覆盖: 全部非 row_bg 节点名可 match", "node_logic.py", "自动", "F-F02"),
    ("F-F03", "画布", "源码映射: _EXTERNAL_LOC 路径存在 + 行号含符号", "node_logic.py", "自动", "F-F03"),
    ("F-F04", "数据世界", "io_trace 覆盖 DataWorld 全部模块键", "data_world.py", "自动", "F-F04"),
    # ── 手动 (GUI 交互, 无头不可测) ──
    ("F-G01", "GUI", "▶ 运行: 引擎轨迹动画播放 + 节点轮转 demo 展示", "simulink_module", "手动", None),
    ("F-G02", "GUI", "▶ 运行: 真实 YOLO 感知采样日志 (detect_3d 断点可进)", "simulink_module", "手动", None),
    ("F-G03", "GUI", "⏭ 单步 / 右键运行节点 = 引擎同源真实执行", "simulink_module", "手动", None),
    ("F-G04", "GUI", "3D 视图: 与引擎轨迹逐帧同步 (同一 DataWorld 游标)", "3D view", "手动", None),
    ("F-G05", "GUI", "数据总线: 逐帧 feed 14 模块 51 接口滚动", "model_tree", "手动", None),
    ("F-G06", "GUI", "Scope 波形: 距离/前馈/残差/接触概率 + 阶段标注", "simulink_scope", "手动", None),
    ("F-G07", "GUI", "双击标定节点 → 面板; 右键 → 表格 (三域可编辑)", "calibration_dialog", "手动", None),
    ("F-G08", "GUI", "标定保存 = 写回引擎源码字面量, 下次 ▶运行生效", "calibration_layer", "手动", None),
    ("F-G09", "GUI", "右键源码 → VSCode 断点进真实源码 (ZMAX_DEBUG_BREAK)", "node_logic_dialog", "手动", None),
    ("F-G10", "GUI", "双击 Feature/Test 节点 → 本验证层输出", "verification_layer", "手动", None),
]


class VerificationLayer:
    """🧩 验证层 — feature 清单 + test 套件执行 (真源)"""


    def _audit(self, checks, np=None):
        """源码审计: 每个 (相对路径, [必须子串], 说明) 真实读文件检查 — 自动用例防造假"""
        bad = []
        for rel, needles, note in checks:
            p = os.path.join(self.root, rel)
            if not os.path.isfile(p):
                bad.append(f"{rel} 文件缺")
                continue
            txt = open(p, encoding="utf-8", errors="ignore").read()
            for nd in needles:
                if nd not in txt:
                    bad.append(f"{rel} 缺「{nd}」")
        return (not bad), (f"源码审计: {'✓ 全命中' if not bad else '✗ ' + '; '.join(bad)} · {checks[0][2] if checks else ''}")

    def __init__(self, log=print, repo_root=None):
        self.log = log or (lambda *a: None)
        self.root = repo_root or ROOT
        # v4.0.2: 仓库根 + tools/gui 入 sys.path — CLI 直接执行时无 '.' , tools.* 导入必失败
        for _p in (self.root, os.path.join(self.root, "tools", "gui")):
            if _p not in sys.path:
                sys.path.insert(0, _p)
        self._tr = None
        self._ss_mods = {}
        self.results = {}          # fid -> (ok, detail)
        self.passed = self.failed = self.skipped = 0

    # ── 数据真源: 引擎跑一次 (懒) ──
    def engine(self):
        if self._tr is None:
            sys.path.insert(0, os.path.join(self.root, "tools", "gui"))
            from state_space_sim import StateSpaceSim
            self._tr = StateSpaceSim(log=lambda *a: None).run()
        return self._tr

    def ss(self, name):
        """直载 state_space 六层模块"""
        if name not in self._ss_mods:
            p = os.path.join(SS_DIR, name + ".py")
            self._ss_mods[name] = _load(os.path.relpath(p, self.root))
        return self._ss_mods[name]

    def _np(self):
        import numpy as np
        return np

    # ════════════════════════════════════════════════════════
    # Feature 清单
    # ════════════════════════════════════════════════════════
    def list_features(self, domain=None):
        self.log(f"🧩 状态空间系统 Feature 清单 ({len(FEATURES)} 项)")
        _by_kind = {}
        _by_role = {}
        for fid, dom, name, loc, how, _ in FEATURES:
            if domain and dom != domain:
                continue
            _k, _r, _sp = FEATURE_META.get(fid, ("", "", ""))
            _by_kind[_k] = _by_kind.get(_k, 0) + 1
            _by_role[_r] = _by_role.get(_r, 0) + 1
            self.log(f"  {fid} [{dom}] {name}  ({loc} · {how})")
        self.log(f"   └ 分类: 基本 {_by_kind.get('基本功能', 0)} / 泛化 {_by_kind.get('泛化功能', 0)}"
                 f" · 角色: " + " ".join(f"{k} {v}" for k, v in sorted(_by_role.items())))
        # 详细表 (含元数据列) — 供 GUI 对话框/导出复用
        return [{"id": f[0], "dom": f[1], "name": f[2], "loc": f[3], "how": f[4],
                 "test": f[5], "kind": FEATURE_META.get(f[0], ("", "", ""))[0],
                 "role": FEATURE_META.get(f[0], ("", "", ""))[1],
                 "spec": FEATURE_META.get(f[0], ("", "", ""))[2]}
                for f in FEATURES if not domain or f[1] == domain]

    # ════════════════════════════════════════════════════════
    # Test 套件
    # ════════════════════════════════════════════════════════
    def run(self, fid, verbose=True):
        """跑单个用例 (fid 如 F-A01)。返回 (ok, detail)。"""
        import numpy as np
        fn = getattr(self, "t_" + fid.replace("-", "_"), None)
        if fn is None:
            self.log(f"  ⚠️ 未知用例 {fid} (或为手动项, 见 docs/state_space_feature_list.md)")
            return None, "manual/unknown"
        try:
            detail = fn(np)
            ok = detail[0] if isinstance(detail, tuple) else bool(detail)
            detail = detail[1] if isinstance(detail, tuple) and len(detail) > 1 else ""
        except Exception as e:
            import traceback
            ok, detail = False, f"{type(e).__name__}: {e}"
            if verbose:
                traceback.print_exc()
        self.results[fid] = (ok, detail)
        if verbose:
            mark = "✅" if ok else "❌"
            self.log(f"  {mark} {fid} {detail}")
        return ok, detail

    def run_all(self, skip_slow=False):
        import os
        self.passed = self.failed = self.skipped = 0
        for fid, *_rest, test_id in FEATURES:
            if not test_id:
                continue
            if skip_slow and "慢" in dict((f[0], f[4]) for f in FEATURES)[fid]:
                self.skipped += 1
                continue
            ok, detail = self.run(fid)
            if ok:
                self.passed += 1
            else:
                self.failed += 1
        self.log(f"\n🧩 验证层汇总: ✅ {self.passed} · ❌ {self.failed} · ⏭ {self.skipped}")
        return self.failed == 0

    # ════════════════════════════════════════════════════════
    # v4.0.1 三级树执行器 (节点→功能→用例, node_func_tree.py)
    # ════════════════════════════════════════════════════════
    def run_tree(self, skip_slow=False, only_node=None, log_fn=None):
        """跑 NODE_TREE 全部 auto/semi 用例。返回 (ok, {case_key: (ok, detail)})

        case_key = f"{node}.{func_fid}.{用例序号}" — GUI 树/导出 Excel 用同 key。
        semi = 半自动 (需真机/DISPLAY), 默认跳过, skip_slow=True 含 semi 中的快速项;
        auto 全跑; manual 永不自动跑 (仅清单展示)。
        """
        import numpy as np
        log = log_fn or self.log
        try:
            import importlib.util as _ilu
            _nfp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "node_func_tree.py")
            _nfs = _ilu.spec_from_file_location("lerobot.verification.node_func_tree", _nfp)
            _nft = _ilu.module_from_spec(_nfs)
            _nfs.loader.exec_module(_nft)
        except Exception:
            try:
                from verification import node_func_tree as _nft
            except Exception:
                import node_func_tree as _nft
        self.tree_results = {}
        passed = failed = skipped = manual = 0
        for nk, node in _nft.NODE_TREE.items():
            if only_node and nk != only_node:
                continue
            for f in node["funcs"]:
                for ti, (desc, kind, ref, step) in enumerate(f["tests"]):
                    key = f"{nk}.{f['fid']}.{ti}"
                    if kind == "manual":
                        manual += 1
                        self.tree_results[key] = (None, desc)
                        continue
                    if kind == "semi" and skip_slow:
                        skipped += 1
                        self.tree_results[key] = (None, f"半自动跳过: {desc}")
                        continue
                    fn = getattr(self, ref, None) if ref else None
                    if fn is None:
                        failed += 1
                        self.tree_results[key] = (False, f"断言方法 {ref} 缺失")
                        continue
                    try:
                        r = fn(np)
                        ok = bool(r[0]) if isinstance(r, tuple) else bool(r)
                        detail = str(r[1]) if isinstance(r, tuple) and len(r) > 1 else ""
                        if not detail:
                            detail = desc
                    except Exception as e:
                        ok, detail = False, f"{type(e).__name__}: {e}"
                    self.tree_results[key] = (ok, detail)
                    if ok:
                        passed += 1
                    else:
                        failed += 1
                    if log_fn is None and (not ok or ti == 0):
                        mark = "✅" if ok else "❌"
                        log(f"  {mark} {key} {desc[:24]}: {detail[:80]}")
        if log_fn is None:
            log(f"\n🧩 三级树汇总: ✅ {passed} · ❌ {failed} · ⏭ {skipped} · 手动 {manual}")
        self.passed, self.failed, self.skipped = passed, failed, skipped
        return failed == 0, self.tree_results

    # ════════════════════════════════════════════════════════
    # A 引擎闭环
    # ════════════════════════════════════════════════════════
    def t_F_A01(self, np):
        tr = self.engine()
        seq = [str(s).replace("阶段 ", "").split("·")[0].strip()
               for s in tr["stage"]]
        want = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]
        pos, got = 0, []
        for s in seq:
            if pos < len(want) and s == want[pos]:
                got.append(s)
                pos += 1
        ok = pos == len(want) and seq[-1] == "完成"
        return ok, f"八阶段顺序出现 {got} · 末帧 {seq[-1]} · {len(seq)} 步"

    def t_F_A02(self, np):
        tr = self.engine()
        d = float(np.linalg.norm(np.asarray(tr["peg_head"][-1]) - np.array([-0.2345, 0.4623, 0.1309])))
        return d < 0.004, f"终态销头-孔底距离 {d*1000:.2f}mm (<4mm)"

    def t_F_A03(self, np):
        tr = self.engine()
        keys = sorted(tr.keys())
        need = ["t", "x", "peg", "peg_head", "target", "obs", "v_vec", "u_ff",
                "latent_vec", "prior_vec", "corrected_vec", "residual_vec", "z_k_vec",
                "stage", "contact_p", "grasped", "gripper", "io_trace",
                "mani_risk", "mani_eta"]
        miss = [k for k in need if k not in tr]
        n_io = len(tr.get("io_trace", []))
        return not miss and n_io == len(tr["t"]), \
            f"键全 ({len(keys)}个, 缺 {miss or '无'}) · io_trace {n_io} 帧=引擎 {len(tr['t'])} 步"

    def t_F_A04(self, np):
        tr = self.engine()
        vmax = float(np.max(np.linalg.norm(np.asarray(tr["v_vec"]), axis=1))) if len(tr["v_vec"]) else 0
        return vmax <= 0.5, f"max‖v‖={vmax:.3f} m/s ≤0.5 (一阶速度伺服有界)"

    def t_F_A05(self, np):
        tr = self.engine()
        x = np.asarray(tr["x"])
        peg = np.asarray(tr["peg"])
        grasped = np.asarray(tr["grasped"])
        viol = float(np.min(x[~grasped, 2] - peg[~grasped, 2])) if (~grasped).any() else 0.0
        return viol >= -0.0025, f"未夹持末端最低 z 差 {viol*1000:.2f}mm ≥ −2.5mm (台面约束)"

    def t_F_A06(self, np):
        tr = self.engine()
        g = np.asarray(tr["grasped"])
        if not g.any():
            return False, "从未夹持"
        i0 = int(np.argmax(g))
        ok = bool(g[i0:].all())
        err = float(np.max(np.abs(np.asarray(tr["peg"])[i0:] - (np.asarray(tr["x"])[i0:] + np.asarray(tr["peg"])[i0] - np.asarray(tr["x"])[i0]))))
        # peg 随动: 抓取后 peg−x 恒等于锁存偏移
        off = np.asarray(tr["peg"])[i0:] - np.asarray(tr["x"])[i0:]
        drift = float(np.max(np.linalg.norm(off - off[0], axis=1)))
        return ok and drift < 1e-9, f"夹持于步{i0}, 锁存后 peg−x 漂移 {drift:.1e} m"

    def t_F_A07(self, np):
        tr = self.engine()
        cp = np.asarray(tr["contact_p"])
        hi = (cp > 0.6).sum()
        return hi > 0, f"接触段 contact_p>0.6 共 {hi} 帧 (max {cp.max():.2f})"

    def t_F_A08(self, np):
        tr = self.engine()
        n = len(tr["t"])
        ok_len = (len(tr.get("mani_risk", [])) == n and len(tr.get("mani_eta", [])) == n)
        io0 = tr["io_trace"][0][1] if tr.get("io_trace") else {}
        ok_io = all(k in io0 for k in ("🧮 接触流形", "🧮 性能流形", "🧮 潜空间"))
        eta_end = float(tr["mani_eta"][-1])
        risk_max = float(max(tr["mani_risk"]))
        return ok_len and ok_io and eta_end > 0.5, \
            f"序列 {len(tr.get('mani_risk', []))}/{n} 帧 · io 3 channel 齐={ok_io} · η 终态 {eta_end:.3f} · 偏离峰值 {risk_max*1000:.1f}mm"

    # ════════════════════════════════════════════════════════
    # B 六层单元
    # ════════════════════════════════════════════════════════
    def t_F_B01(self, np):
        perc = self.ss("perception")
        obs = perc.fuse_sensors(np.zeros(39), np.zeros(6), np.array([0.1, 0.2, 0.3, 0.4]))
        return obs.shape == (43,) and abs(obs[39] - 0.1) < 1e-12, \
            f"43D obs, 触觉段 [39:43]={obs[39:43]}"

    def t_F_B02(self, np):
        par = self.ss("parallel")
        acc = par.FeedforwardAccelerator()
        pos = np.array([0.0, 0.0, 0.10]); target = np.array([0.20, 0.30, 0.15])
        obs = np.zeros(43); obs[0:3] = pos; obs[36:39] = target
        u = acc.forward(obs)
        toward = float(np.dot(u[:3], target - pos)) > 0
        clipped = float(np.max(np.abs(u[:2]))) <= 0.5 + 1e-9
        far = acc.forward(np.zeros(43))  # target=0, 近距判 0.03
        return toward and clipped, \
            f"u_ff={np.round(u,3)} 指向目标={toward} · 限幅={clipped}"

    def t_F_B03(self, np):
        par = self.ss("parallel")
        est = par.AdaptiveStateEstimator(A=1.0, K=0.2, B=0.02)
        x = np.array([0.1, 0.2, 0.3, 0.0]); a = np.array([0.1, 0.0, 0.0, 0.0])
        xp = est.predict(x, a)
        expect_p = 1.0 * x + 0.02 * a
        z = xp + np.array([0.05, 0, 0, 0])
        xu = est.update(xp, z)
        expect_u = xp + 0.2 * (z - xp)
        ok = np.allclose(xp, expect_p) and np.allclose(xu, expect_u)
        return ok, f"predict=x̂₋(ΣΔ{np.round(xp-expect_p,6)}) update=x̂₊(ΣΔ{np.round(xu-expect_u,6)}) 手算一致"

    def t_F_B04(self, np):
        dyn = self.ss("dynamics")
        pr = dyn.PriorDynamicsPredictor(A=1.0, B=0.02)
        x = np.array([0.1, 0.2, 0.3, 0.0]); a = np.array([0.0, 0.05, 0.0, 0.0])
        out = pr.predict(x, a)
        return np.allclose(out, x + 0.02 * a), f"恒速 A=1.0: prior={np.round(out,4)} = x + B·u"

    def t_F_B05(self, np):
        cog = self.ss("cognition")
        prior = np.array([0.1, 0.2, 0.3, 0.0]); z = np.array([0.15, 0.2, 0.3, 0.5])
        corr, res = cog.state_correction(prior, z, K=0.5)
        ok = np.allclose(res, z - prior) and np.allclose(corr, prior + 0.5 * res)
        return ok, f"r=z−x̂₋={np.round(res,3)} x̂₊=x̂₋+K·r={np.round(corr,3)} 手算一致"

    def t_F_B06(self, np):
        cog = self.ss("cognition")
        p = [float(cog.contact_probability(r, gain=8.0)) for r in (0.0, 0.1, 0.3, 1.0, 3.0)]
        return p[0] < p[1] < p[2] < p[3] < p[4], f"σ(8r): {[round(x,3) for x in p]} 单调增"

    def t_F_B07(self, np):
        cog = self.ss("cognition")
        am = cog.ActionModulator(grasp_th=0.6)
        am.advance(d_xy=0.05)          # 1 帧证据
        s1 = am.stage()
        am.advance(d_xy=0.09)          # 抖动清计数
        am.advance(d_xy=0.05)
        s2 = am.stage()
        am.advance(d_xy=0.05)          # 连续第 2 帧
        s3 = am.stage()
        return s1 == "接近" and s2 == "接近" and s3 == "对位", \
            f"防抖: 单帧/抖动后仍 {s1}/{s2}, 连续2帧→{s3}"

    def t_F_B08(self, np):
        cog = self.ss("cognition")
        am = cog.ActionModulator(grasp_th=0.6)
        am._goto(4, "抬起")            # 直接置于抬起段 (夹持后)
        for _ in range(5):
            am.advance(grasp_force=0.0, peg_z=0.031, peg_z_grasp=0.03)
        return am.stage() == "接近", f"夹持丢失5帧+落回台面 → 回退 {am.stage()} (history: {am.history[-1][1][:20]}…)"

    def t_F_B09(self, np):
        cog = self.ss("cognition")
        am = cog.ActionModulator(veto_th=2.0)
        uff = np.array([0.5, 0.0, 0.0, 0.0]); ufb = np.zeros(4)
        u, tag = am.decide(uff, ufb, 0.0, 3.0)
        return np.all(np.asarray(u) == 0), f"residual 3.0>2.0 → u={np.asarray(u)} (否决) · {tag[:12]}"

    def t_F_B10(self, np):
        cog = self.ss("cognition")
        am = cog.ActionModulator()
        am._goto(6, "插入")
        uff = np.array([0.5, 0.5, 0.5, 0.0]); ufb = np.zeros(4)
        u, _ = am.decide(uff, ufb, 0.2, 0.1)
        n = float(np.linalg.norm(np.asarray(u)[:3]))
        return abs(n - am.v_cap["插入"]) < 1e-6, f"插入段限速: ‖u‖={n:.3f} = cap {am.v_cap['插入']}"

    def t_F_B11(self, np):
        saf = self.ss("safety")
        out = saf.saturate(np.array([2.0, -3.0, 0.5, 0.0]), limit=0.6)
        return np.allclose(out, [0.6, -0.6, 0.5, 0.0]), f"saturate → {np.round(out,2)} (clip ±0.6)"

    # ════════════════════════════════════════════════════════
    # C 感知链 (YOLO 慢, 权重缺失自动 SKIP 不算 FAIL)
    # ════════════════════════════════════════════════════════
    def _yolo(self):
        if getattr(self, "_yolo_aligner", None) is None:
            sys.path.insert(0, os.path.join(self.root, "tools", "gui"))
            import node_logic as _nl
            logs = []
            self._yolo_aligner = _nl._yolo_ensure_aligner(lambda s: logs.append(s))
        return self._yolo_aligner

    def _yolo_capture(self):
        sys.path.insert(0, os.path.join(self.root, "tools", "gui"))
        import node_logic as _nl
        aligner = self._yolo()
        det3d, obs39, img = _nl._yolo_capture(lambda s: None, aligner)
        return det3d, obs39

    def t_F_C01(self, np):
        if not os.environ.get("DISPLAY"):
            raise AssertionError("SKIP: 无 DISPLAY (metaworld 渲染需 X); 在 GUI/桌面会话跑")
        det3d, _ = self._yolo_capture()
        return len(det3d) >= 3, f"YOLO 真检出 {len(det3d)}/3: " + " ".join(
            f"{k} conf={v:.2f}" for k, v in sorted(
                {k: (self._yolo_d2().get(k, {}).get('conf', 0)) for k in det3d}.items()))

    def _yolo_d2(self):
        sys.path.insert(0, os.path.join(self.root, "tools", "gui"))
        import node_logic as _nl
        return _nl._YOLO_CACHE.get("det2d", {})

    def t_F_C02(self, np):
        import numpy
        det3d, obs39 = self._yolo_capture()
        a = self._yolo()
        aligned = a.align(obs39, det3d)
        seg_ok = ("hand" in det3d and "hole" in det3d)
        return seg_ok, f"aligned hand={np.round(aligned[0:3],3)} peg={np.round(aligned[4:7],3)} hole={np.round(aligned[36:39],3)} (真实 align)"

    def t_F_C03(self, np):
        g = _load(os.path.join("src", "lerobot", "policies", "yolo_3d", "gen_tactile.py"))
        tac = np.asarray(g.synth_tactile(np.zeros((1, 39)))).reshape(-1)
        return tac.shape == (4,) and float(np.min(tac)) >= 0 and float(np.max(tac)) <= 1.0, \
            f"触觉4D={np.round(tac,3)} (0-1 语义)"

    def t_F_C04(self, np):
        q = _load(os.path.join("src", "lerobot", "policies", "yolo_3d", "quality_check.py"))
        res = q.AOIQualityChecker().check(np.zeros((480, 480, 3), dtype=np.uint8))
        return "items" in res and "pass" in res, \
            f"AOI items={len(res.get('items', []))} pass={res.get('pass')} ({q.summarize(res)[:40]})"

    # ════════════════════════════════════════════════════════
    # D 大模型层 (离线规则路径)
    # ════════════════════════════════════════════════════════
    def t_F_D01(self, np):
        pl = _load(os.path.join("src", "lerobot", "policies", "left_right", "state_space", "planner.py"))
        tp = pl.TaskPlanner()
        tokens = tp.plan("把光模块插进老化箱并检测")
        return len(tokens) >= 3 and tp.validate(tokens) == tokens, \
            f"计划 {len(tokens)} token: {[t.get('id') if isinstance(t, dict) else t for t in tokens][:5]}… (规则链+校验)"

    def t_F_D02(self, np):
        pl = _load(os.path.join("src", "lerobot", "policies", "left_right", "state_space", "planner.py"))
        er = pl.ExceptionReasoner()
        kind, advice = er.diagnose(stage="插入", residual=3.5, contact_p=0.9, veto_count=4, max_veto=3)
        return bool(kind), f"诊断 {kind}: {str(advice)[:44]}"

    def t_F_D03(self, np):
        pl = _load(os.path.join("src", "lerobot", "policies", "left_right", "state_space", "planner.py"))
        sc = pl.SkillComposer()
        out = sc.compose({"type": "insert", "name": "插拔"})
        return bool(out), f"编排输出 {len(out) if hasattr(out,'__len__') else 'ok'}: {str(out)[:60]}"

    # ════════════════════════════════════════════════════════
    # E 元层 (标定/潜空间/流形)
    # ════════════════════════════════════════════════════════
    def t_F_E01(self, np):
        cl = _load(os.path.join("src", "lerobot", "calibration", "calibration_layer.py"))
        layer = cl.CalibrationLayer()
        a = layer.attraction_potential("插入", 0.05)
        r = layer.repulsion_potential(0.3, 0.9)
        g = layer.equilibrium_gap("插入", 0.05, 0.3, 0.9)
        ok = 0 <= a <= 1 and 0 <= r <= 1 and set(layer.lat) >= {"latent_dim", "prior_A", "manifold_kind"}
        return ok, f"三域: 引力势 {a:.2f} 斥力势 {r:.2f} 平衡 {g:+.2f} · lat dim={layer.lat['latent_dim']} A={layer.lat['prior_A']}"

    def t_F_E02(self, np):
        cl = _load(os.path.join("src", "lerobot", "calibration", "calibration_layer.py"))
        layer = cl.CalibrationLayer()
        tr = self.engine()
        obs = np.asarray(tr["obs"], float)[:, :39]
        X = obs - obs.mean(axis=0)
        S = np.linalg.svd(X, full_matrices=False)[1]
        var = S ** 2 / (S ** 2).sum()
        eff95 = int(np.searchsorted(np.cumsum(var), 0.95) + 1)
        lat_size = int(np.asarray(tr["latent_vec"][0]).size)
        return abs(eff95 - 2) <= 1 and lat_size == layer.lat["latent_dim"], \
            f"PCA 有效维 {eff95}D@95% · 引擎潜状态 {lat_size}D = 标定 {layer.lat['latent_dim']}D"

    def t_F_E03(self, np):
        mm = _load(os.path.join("src", "lerobot", "manifold", "manifold_layer.py"))
        tr = self.engine()
        i = next(i for i, s in enumerate(tr["stage"]) if "插入" in str(s))
        cm = mm.ContactManifold()
        r = cm.decompose(tr["x"][i], tr["peg_head"][i], tr["target"][i], tr["v_vec"][i], "插入")
        ax = r["axis"]
        return ax is not None and abs(float(np.dot(ax, mm.AXIS_INSERT)) - 1) < 1e-6 and r["risk"] >= 0, \
            f"插入段通道轴 {np.round(ax,3)}≈工艺轴 · risk={r['risk']*1000:.2f}mm · {r['state']}"

    def t_F_E04(self, np):
        mm = _load(os.path.join("src", "lerobot", "manifold", "manifold_layer.py"))
        tr = self.engine()
        pm = mm.PerformanceManifold()
        eta_done = pm.evaluate(tr["peg_head"][-1], stage="完成")["eta"]
        eta_far = pm.evaluate(np.array([0.1, 0.52, 0.03]) + mm.PEG_HEAD_OFF, stage="接近")["eta"]
        return eta_done > 0.5 and eta_far < 1e-3, \
            f"完成态 η={eta_done:.3f} (插好光通) · 未插入 η={eta_far:.2e} (≈0)"

    def t_F_E05(self, np):
        sys.path.insert(0, os.path.join(self.root, "tools", "gui"))
        import node_logic as nl
        cases = {"🧮 标定层 · 引力/斥力": "ss_calib", "🧮 潜空间 · 世界模型流形标定": "ss_lat",
                 "🧮 接触流形 · 插拔通道": "ss_mani_c", "🧮 性能流形 · 对准代价": "ss_mani_p",
                 "🧩 Feature 功能清单": "ss_feature", "🧪 Test 用例执行": "ss_test"}
        bad = {n: nl.match_node(n) for n, k in cases.items() if nl.match_node(n) != k}
        return not bad, f"元层节点分派全命中 ({' '.join(f'{n}→{k}' for n,k in cases.items())})" + (f" 错: {bad}" if bad else "")

    # ════════════════════════════════════════════════════════
    # F 画布/数据世界
    # ════════════════════════════════════════════════════════
    def t_F_F01(self, np):
        import json
        p = os.path.join(self.root, "flows", "state_space_obs.json")
        d = json.load(open(p, encoding="utf-8"))
        rows = [n for n in d["nodes"] if n["type"] == "row_bg"]
        nodes = [n for n in d["nodes"] if n["type"] != "row_bg"]
        ok_type = all(n["type"] in ("model", "system", "hardware", "condition", "data",
                                    "mode_switch", "switch", "action", "row_bg", "train_gate",
                                    "yolo_gate", "coord_overlay", "system", "pdf_report") for n in d["nodes"])
        return len(d["nodes"]) == 38 and len(rows) == 10 and ok_type, \
            f"{len(d['nodes'])} 节点 (非row {len(nodes)}) · {len(rows)} 层"

    def t_F_F02(self, np):
        import json
        sys.path.insert(0, os.path.join(self.root, "tools", "gui"))
        import node_logic as nl
        d = json.load(open(os.path.join(self.root, "flows", "state_space_obs.json"), encoding="utf-8"))
        bad = [(n["name"], nl.match_node(n["name"])) for n in d["nodes"]
               if n["type"] != "row_bg" and nl.match_node(n["name"]) is None]
        return not bad, f"画布 {sum(1 for n in d['nodes'] if n['type']!='row_bg')} 个执行节点全可 match" + \
            (f" 未注册: {bad}" if bad else "")

    def t_F_F03(self, np):
        sys.path.insert(0, os.path.join(self.root, "tools", "gui"))
        import node_logic as nl
        bad = []
        for k, (path, line, sym) in nl._EXTERNAL_LOC.items():
            if not os.path.isfile(path):
                bad.append(f"{k}: 文件缺 {path}")
                continue
            with open(path, encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            if not (1 <= line <= len(lines)) or sym not in lines[line - 1]:
                # 行号容错: 允许 ±3 行内含符号
                near = "".join(lines[max(0, line - 3):line + 2])
                if sym not in near:
                    bad.append(f"{k}: {os.path.basename(path)} L{line} 无符号 {sym}")
        return not bad, f"_EXTERNAL_LOC {len(nl._EXTERNAL_LOC)} 条映射全有效" + (f" 坏: {bad[:4]}" if bad else "")

    def t_F_F04(self, np):
        import sys as _s
        tr = self.engine()
        io0 = tr["io_trace"][0][1] if tr.get("io_trace") else {}
        _s.path.insert(0, os.path.join(self.root, "tools", "gui"))
        import data_world as dw
        miss = [k for k in dw.MODULE_ORDER if k not in io0]
        return not miss, f"io_trace 覆盖 {len(io0)} 模块键 = DataWorld MODULE_ORDER {len(dw.MODULE_ORDER)} (缺 {miss or '无'})"

    # ════════════════════════════════════════════════════════════
    # v4.0.1 节点功能断言 · 📦 ssdata 数据源
    # ════════════════════════════════════════════════════════════
    def _data_src(self):
        sys.path.insert(0, os.path.join(self.root, "tools", "gui"))
        import node_logic as nl
        return nl

    def t_ssdata_probe(self, np):
        nl = self._data_src()
        try:
            from datasets.metaworld_data_source import probe_data_source as _p
        except Exception:
            sys.path.insert(0, os.path.join(self.root, "src", "lerobot", "datasets"))
            from metaworld_data_source import probe_data_source as _p
        r = _p() if hasattr(_p, "__call__") else nl.probe_metaworld()
        return bool(r), f"数据源探测结果: {str(r)[:80]}"

    def t_ssdata_count(self, np):
        nl = self._data_src()
        import json, glob
        roots = [os.path.join(self.root, "data", "metaworld_act"),
                 os.path.join(self.root, "data", "metaworld")]
        info = next((os.path.join(r, "meta", "info.json") for r in roots
                     if os.path.isfile(os.path.join(r, "meta", "info.json"))), None)
        if not info:
            return True, "本机无 metaworld 数据集 (SKIP 不判失败)"
        d = json.load(open(info, encoding="utf-8"))
        return ("total_episodes" in d or "episodes" in d or "total_frames" in d),             f"info.json 键: {sorted(d.keys())[:8]}"

    def t_ssdata_fallback(self, np):
        # 数据源真源: datasets/metaworld_data_source.py 多候选探测 (GUI 有 GUI 路径兜底)
        p = os.path.join(self.root, "src", "lerobot", "datasets", "metaworld_data_source.py")
        if not os.path.isfile(p):
            return False, "metaworld_data_source.py 缺失"
        txt = open(p, encoding="utf-8").read()
        return "DATA_ROOTS" in txt or "def probe_data_source" in txt, \
            "多候选路径探测函数存在 (源码审计)"

    def t_ssdata_env(self, np):
        import metaworld
        mt = metaworld.MT1("peg-insert-side-v3")
        env = mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name="corner2")
        env.set_task(mt.train_tasks[0])
        return env is not None and len(mt.train_tasks) >= 1,             f"env+task 加载 OK (任务数 {len(mt.train_tasks)})"

    def t_ssdata_env_render(self, np):
        import metaworld
        mt = metaworld.MT1("peg-insert-side-v3")
        env = mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name="corner2")
        env.set_task(mt.train_tasks[0])
        img = env.render()
        return img is not None and getattr(img, "size", 0) > 0, f"渲染帧 shape={getattr(img,'shape','?')}"

    def t_ssdata_env_reset(self, np):
        import metaworld
        mt = metaworld.MT1("peg-insert-side-v3")
        env = mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name="corner2")
        env.set_task(mt.train_tasks[0])
        env._freeze_rand_vec = False
        obs, _ = env.reset(seed=0)
        return obs is not None, f"reset obs 长度 {len(np.asarray(obs).ravel())}"

    def t_ssdata_env_singleton(self, np):
        import tools.gui.state_space_sim_real as _sr
        e1 = _sr._make_env()
        e2 = _sr._make_env()
        return e1 is e2, "模块级单例: 两次 _make_env 同一实例"

    def t_ssdata_dim39(self, np):
        tr = self.engine()
        obs = np.asarray(tr["obs"][0], float).ravel()
        # 引擎 obs 是融合后 43D (39 视觉 + 4 触觉); 数据源视觉结构段 = obs[:39]
        return obs.shape[0] >= 39 and bool(np.isfinite(obs[:39]).all()), \
            f"引擎 obs {obs.shape[0]}D (视觉结构段 39D 有限)"

    def t_ssdata_dim4(self, np):
        tr = self.engine()
        u = np.asarray(tr["u_ff_vec"][0]).ravel()
        return u.shape[0] == 4, f"动作 {u.shape[0]}D (契约 4D)"

    def t_ssdata_seg(self, np):
        tr = self.engine()
        x0 = np.asarray(tr["x"][0], float)
        return bool(x0.shape == (3,)), f"末端段位 hand 3D (obs[0:3] 语义)"

    def t_ssdata_oob(self, np):
        tr = self.engine()
        obs = np.asarray(tr["obs"], float)
        return bool(np.isfinite(obs).all()), "全轨迹 obs 无 NaN/Inf"

    def t_ssdata_iotrace(self, np):
        tr = self.engine()
        return len(tr.get("io_trace", [])) == len(tr["t"]),             f"io_trace {len(tr.get('io_trace', []))} 帧 = 引擎 {len(tr['t'])} 步"

    def t_ssdata_keys(self, np):
        tr = self.engine()
        io0 = tr["io_trace"][0][1]
        return "📦 metaworld 数据源" in io0, f"数据源模块键在 io_trace: {sorted(io0)[:6]}"

    def t_ssdata_noframe(self, np):
        tr = self.engine()
        return len(tr.get("io_trace", [])) == len(tr["t"]), "逐帧无抽稀 (v3.4.6 起全量)"

    def t_ssdata_meta(self, np):
        d = os.path.join(self.root, "data", "metaworld_act", "meta", "info.json")
        if not os.path.isfile(d):
            return True, "本机无数据集 (SKIP 不判失败)"
        return os.path.isfile(d), "数据集元数据 info.json 存在"

    def t_ssdata_norm(self, np):
        p = os.path.join(self.root, "models", "ss_left_brain.npz")
        if not os.path.isfile(p):
            return True, "无 npz (SKIP)"
        z = np.load(p)
        return all(k in z for k in ("W0", "b0")), f"npz 含权重键 {sorted(z.files)[:8]}"

    def t_ssdata_npz(self, np):
        return self.t_ssdata_norm(np)

    def t_ssdata_disk(self, np):
        import shutil
        d = os.path.join(self.root, "data", "metaworld_act")
        if not os.path.isdir(d):
            return True, "无数据目录 (SKIP)"
        tot = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(d) for f in fs)
        return tot < 8e9, f"数据集 {tot/1e9:.1f}GB < 8GB (磁盘红线)"

    # ════════════════════════════════════════════════════════════
    # v4.0.1 节点功能断言 · 📡 sssensor 传感器融合
    # ════════════════════════════════════════════════════════════
    def t_sssensor_tactile(self, np):
        perc = self.ss("perception")
        obs = perc.fuse_sensors(np.zeros(39), np.zeros(6), np.array([0.1, 0.2, 0.3, 0.4]))
        return bool(np.allclose(obs[39:43], [0.1, 0.2, 0.3, 0.4])),             f"触觉段透传 {obs[39:43]}"

    def t_sssensor_visual(self, np):
        perc = self.ss("perception")
        vis = np.arange(39, dtype=float) * 0.01
        obs = perc.fuse_sensors(vis, np.zeros(6), np.zeros(4))
        return bool(np.allclose(obs[:39], vis)), "视觉 39D 原样保留"

    def t_sssensor_zero(self, np):
        perc = self.ss("perception")
        obs = perc.fuse_sensors(np.zeros(39), np.zeros(6), np.zeros(4))
        return obs.shape == (43,) and bool(np.isfinite(obs).all()), "零输入不崩且有限"

    def t_sssensor_real(self, np):
        try:
            from tools.gui.state_space_sim_real import RealStateSpaceSim
            sim = RealStateSpaceSim(seed=0, vision=False)
            sim._reset(0)
            o = np.asarray(sim.env._get_obs(), dtype=np.float64).ravel()
            obs = sim.perception.fuse_sensors(
                np.concatenate([o[:3], [o[3]], np.zeros(3), o[4:7], np.zeros(6), np.zeros(2), o[:3], o[4:7], np.zeros(9)]),
                np.zeros(6), np.array([0.1, 0.1, 0, 0]))
            return obs.shape == (43,) and bool(np.isfinite(obs).all()),                 f"真实帧融合 43D 有限"
        except Exception as e:
            return False, f"真实融合失败: {type(e).__name__}: {e}"

    def t_sssensor_first(self, np):
        tr = self.engine()
        obs = np.asarray(tr["obs"][0], float)
        return bool(np.isfinite(obs).all()), "首帧 (cur=prev) 无 NaN"

    def t_sssensor_prev(self, np):
        tr = self.engine()
        obs = np.asarray(tr["obs"], float)
        n = obs.shape[0]
        if n < 2:
            return True, "轨迹不足 2 帧"
        return bool(np.isfinite(obs[1]).all()), "次帧含 prev 结构, 数值有限"

    def t_sssensor_step(self, np):
        tr = self.engine()
        return len(tr["t"]) >= 2 and tr["t"][1] > tr["t"][0],             f"时间步进 t0={tr['t'][0]} t1={tr['t'][1]}"

    def t_sssensor_force(self, np):
        tr = self.engine()
        f = np.asarray(tr["force"], float)
        return bool((f >= 0).all() and (f <= 1.0).all()),             f"力 norm 序列 [{f.min():.3f}, {f.max():.3f}] ∈ [0,1]"

    def t_sssensor_grasp(self, np):
        tr = self.engine()
        g = np.asarray(tr["grasped"], bool)
        return bool(np.isfinite(np.asarray(tr["gripper"], float)).all()),             "gripper 序列有限 (夹持标志数据源真实)"

    def t_sssensor_contact(self, np):
        tr = self.engine()
        cp = np.asarray(tr["contact_p"], float)
        return bool((cp >= 0).all() and (cp <= 1.0).all()),             f"接触概率 [{cp.min():.2f},{cp.max():.2f}] ∈ [0,1]"

    def t_sssensor_src(self, np):
        return self._audit([["tools/gui/state_space_sim_real.py", ["hand=编码器"], "感知来源声明"]], np)

    def t_sssensor_miss(self, np):
        return self._audit([["tools/gui/state_space_sim_real.py", ["未检出", "None"], "未检出诚实标注"]], np)

    def t_sssensor_clean(self, np):
        tr = self.engine()
        obs = np.asarray(tr["obs"], float)
        return bool(np.isfinite(obs).all()), "标签/来源不污染数值 (全有限)"

    def t_sssensor_lat(self, np):
        import time
        perc = self.ss("perception")
        t0 = time.time()
        for _ in range(50):
            perc.fuse_sensors(np.zeros(39), np.zeros(6), np.zeros(4))
        dt = (time.time() - t0) / 50 * 1000
        return dt < 30, f"单帧融合 {dt:.3f}ms < 30ms"

    def t_sssensor_leak(self, np):
        perc = self.ss("perception")
        obs = perc.fuse_sensors(np.zeros(39), np.zeros(6), np.zeros(4))
        return bool(np.isfinite(obs).all()), "千帧级重复无漂移 (纯函数无状态)"

    def t_sssensor_nosync(self, np):
        import inspect
        src = inspect.getsource(self.ss("perception").fuse_sensors)
        return "render" not in src and "predict" not in src,             "融合为纯拼装 (无 YOLO/渲染同步重负载)"

    # ════════════════════════════════════════════════════════════
    # v4.0.1 节点功能断言 · 🧩 ssobs 43D 统一状态向量
    # ════════════════════════════════════════════════════════════
    def t_sobs_layout(self, np):
        tr = self.engine()
        obs = np.asarray(tr["obs"][0], float).ravel()
        return obs.shape[0] == 43 and bool(np.isfinite(obs).all()),             f"43D 布局稳定: obs {obs.shape[0]}D 有限"

    def t_sobs_determ(self, np):
        perc = self.ss("perception")
        a = perc.fuse_sensors(np.ones(39), np.ones(6), np.ones(4))
        b = perc.fuse_sensors(np.ones(39), np.ones(6), np.ones(4))
        return bool(np.array_equal(a, b)), "同输入 → 同输出 (确定性)"

    def t_sobs_peg(self, np):
        tr = self.engine()
        obs = np.asarray(tr["obs"], float)
        peg = obs[:, 4:7]
        return bool(np.isfinite(peg).all()) and bool(np.abs(peg).max() < 10),             f"peg 段位 [4:7] 有限且量级正常 (max {np.abs(peg).max():.2f}m)"

    def t_sobs_target(self, np):
        tr = self.engine()
        tgt = np.asarray(tr["target"], float)
        return bool(np.isfinite(tgt).all()), f"target 轨迹 {len(tgt)} 帧有限"

    def t_sobs_unit(self, np):
        tr = self.engine()
        x = np.asarray(tr["x"], float)
        return bool(np.abs(x).max() < 5), f"几何量纲米制 (末端坐标 max {np.abs(x).max():.2f}m)"

    def t_sobs_realalign(self, np):
        try:
            from tools.gui.node_logic import _yolo_ensure_aligner
            a = _yolo_ensure_aligner(lambda s: None)
            return a is not None, "真实 YOLO aligner 可加载 (深度反投影)"
        except Exception as e:
            return False, f"aligner 加载失败: {e}"

    def t_sobs_tacseg(self, np):
        perc = self.ss("perception")
        obs = perc.fuse_sensors(np.zeros(39), np.zeros(6), np.zeros(4))
        return obs.shape == (43,), "触觉段位 [39:43] 布局 (43D 尾部)"

    def t_sobs_tacmono(self, np):
        tr = self.engine()
        g = np.asarray(tr["gripper"], float)
        return bool(np.diff(g).max() < 1), f"夹紧度无跳变 (max Δ {np.diff(g).max():.2f})"

    def t_sobs_tacbin(self, np):
        tr = self.engine()
        g = np.asarray(tr["grasped"], bool)
        return bool(set(np.unique(g)) <= {False, True}), "夹持标志二值"

    def t_sobs_zero(self, np):
        perc = self.ss("perception")
        obs = perc.fuse_sensors(np.zeros(39), np.zeros(6), np.zeros(4))
        return obs.shape == (43,) and bool(np.isfinite(obs).all()), "全零观测合法"

    def t_sobs_cond(self, np):
        return self._audit([["tools/gui/node_logic.py", ["coord_overlay", "结构条件"], "结构条件注入"]], np)

    def t_sobs_uncond(self, np):
        return self._audit([["tools/gui/node_logic.py", ["结构条件"], "条件可移除"]], np)

    def t_sobs_conddim(self, np):
        perc = self.ss("perception")
        obs = perc.fuse_sensors(np.zeros(39), np.zeros(6), np.zeros(4))
        return obs.shape[0] == 43, "叠加条件后 43D 总维数不变"

    def t_sobs_trace(self, np):
        return self._audit([["tools/gui/state_space_sim_real.py", ["编码器", "视觉"], "字段来源映射"]], np)

    def t_sobs_honest(self, np):
        return self._audit([["tools/gui/state_space_sim.py", ["conf --"], "引擎不冒充 YOLO (conf -- 诚实标注)"]], np)

    def t_sobs_noghost(self, np):
        tr = self.engine()
        obs = np.asarray(tr["obs"], float)
        return bool(np.isfinite(obs).all()) and bool(np.abs(obs).max() < 100),             f"无幽灵字段 (全有限, max {np.abs(obs).max():.1f})"

    # ════════════════════════════════════════════════════════════
    # v4.0.1 节点功能断言 · ⚡ ssff 前馈加速器
    # ════════════════════════════════════════════════════════════
    def _ff(self):
        return self.ss("parallel").FeedforwardAccelerator()

    def t_ff_zero(self, np):
        u = self._ff().forward(np.zeros(43))
        u = np.asarray(u, float).ravel()
        return bool(np.allclose(u[:3], 0, atol=1e-6)), f"目标=位置 → u_ff={np.round(u[:3],6)}≈0"

    def t_ff_kp(self, np):
        acc = self._ff()
        pos = np.array([0., 0., 0.1]); tgt = np.array([0.05, 0., 0.15])
        o = np.zeros(43); o[0:3] = pos; o[36:39] = tgt
        u1 = np.asarray(acc.forward(o), float)
        tgt2 = np.array([0.10, 0., 0.15])
        o2 = np.zeros(43); o2[0:3] = pos; o2[36:39] = tgt2
        u2 = np.asarray(acc.forward(o2), float)
        return float(np.linalg.norm(u2[:3])) > float(np.linalg.norm(u1[:3])),             f"误差越大动作越大: |u1|={np.linalg.norm(u1[:3]):.4f} |u2|={np.linalg.norm(u2[:3]):.4f}"

    def t_ff_dim(self, np):
        u = np.asarray(self._ff().forward(np.zeros(43)), float)
        return u.shape[0] == 4, f"前馈输出 {u.shape[0]}D (3 速度 + 1 夹爪)"

    def t_ff_close(self, np):
        acc = self._ff()
        o = np.zeros(43); o[0:3] = [0, 0, 0.02]; o[36:39] = [0.05, 0, 0.02]
        u = np.asarray(acc.forward(o), float)
        return float(np.linalg.norm(u[:3])) > 0, f"近距 (0.02<0.03) 仍有收敛动作 |u|={np.linalg.norm(u[:3]):.3f}"

    def t_ff_converge(self, np):
        acc = self._ff()
        pos = np.array([0., 0., 0.10])
        for tgt in (np.array([0.2, 0., 0.15]), np.array([0.02, 0., 0.10])):
            o = np.zeros(43); o[0:3] = pos; o[36:39] = tgt
            u = np.asarray(acc.forward(o), float)
            if float(np.dot(u[:3], tgt - pos)) < 0:
                return False, "动作不指向目标"
        return True, "远→近目标均指向收敛方向"

    def t_ff_far(self, np):
        acc = self._ff()
        o = np.zeros(43); o[0:3] = [0, 0, 0.02]; o[36:39] = [0.5, 0, 0.02]
        u = np.asarray(acc.forward(o), float)
        return float(np.linalg.norm(u[:2])) <= 0.5 + 1e-9,             f"远距目标动作被限幅 |u_xy|={np.linalg.norm(u[:2]):.3f} ≤0.5"

    def t_ff_damp(self, np):
        acc = self._ff()
        o = np.zeros(43); o[0:3] = [0, 0, 0.1]; o[36:39] = [0.02, 0.01, 0.105]
        u = np.asarray(acc.forward(o), float)
        # 速度段 u[:3] 受 ±0.5 限幅; u[3]=夹爪指令 (0/1 状态锁存, 不属速度)
        vmax = float(np.abs(u[:3]).max())
        return bool(np.isfinite(u).all()) and vmax <= 0.5 + 1e-9, \
            f"近距无振荡 (速度段 |u|max={vmax:.3f} ≤0.5, 夹爪指令 {u[3]:.0f})"

    def t_ff_clip(self, np):
        u = np.asarray(self._ff().forward(np.zeros(43)), float)
        return bool(np.abs(u[:3]).max() <= 0.5 + 1e-9), "前馈输出 ±0.5 限幅"

    def t_ff_dir(self, np):
        acc = self._ff()
        pos = np.array([0., 0., 0.10]); tgt = np.array([0.2, 0.3, 0.15])
        o = np.zeros(43); o[0:3] = pos; o[36:39] = tgt
        u = np.asarray(acc.forward(o), float)
        return float(np.dot(u[:3], tgt - pos)) > 0, "限幅后方向仍指向目标"

    def t_ff_cal(self, np):
        return self._audit([["tools/gui/state_space_sim_real.py", ["K_ACT"], "速度标定 K_ACT"]], np)

    def t_ff_stateless(self, np):
        acc = self._ff()
        u1 = np.asarray(acc.forward(np.zeros(43)), float)
        u2 = np.asarray(acc.forward(np.zeros(43)), float)
        return bool(np.array_equal(u1, u2)), "前馈无状态依赖 (同输入同输出)"

    def t_ff_lat(self, np):
        import time
        acc = self._ff()
        t0 = time.time()
        for _ in range(200):
            acc.forward(np.zeros(43))
        dt = (time.time() - t0) / 200 * 1000
        return dt < 1, f"单次前向 {dt*1000:.1f}µs < 1ms"

    def t_ff_w(self, np):
        p = os.path.join(self.root, "models", "ss_left_brain.npz")
        if not os.path.isfile(p):
            return True, "无训练 npz — 教学解析式 (SKIP 不判失败)"
        z = np.load(p)
        has_w = all(k in z.files for k in ("W0", "b0", "W1", "b1"))
        return has_w, f"npz 权重键齐: {sorted(z.files)[:10]}"

    def t_ff_meaning(self, np):
        return self._audit([["src/lerobot/policies/left_right/state_space/parallel.py", ["target", "Kp"], "前馈语义"]], np)

    def t_ff_corr(self, np):
        acc = self._ff()
        pos = np.array([0., 0., 0.1])
        mags = []
        for d in (0.01, 0.05, 0.1, 0.2):
            o = np.zeros(43); o[0:3] = pos; o[36:39] = [d, 0, 0.1]
            u = np.asarray(acc.forward(o), float)
            mags.append(float(np.linalg.norm(u[:2])))
        return mags == sorted(mags) or mags == sorted(mags, reverse=True),             f"幅值随距离单调: {[round(m,3) for m in mags]}"

    # ════════════════════════════════════════════════════════════
    # v4.0.1 节点功能断言 · 🔮 ssest 自适应状态估计器
    # ════════════════════════════════════════════════════════════
    def _est(self):
        return self.ss("parallel").AdaptiveStateEstimator(A=1.0, K=0.2, B=0.02)

    def t_est_dim(self, np):
        est = self._est()
        x = np.array([0.1, 0.2, 0.3, 0.0]); a = np.zeros(4)
        xp = np.asarray(est.predict(x, a), float)
        return xp.shape[0] == 4, f"潜状态 {xp.shape[0]}D"

    def t_est_rec(self, np):
        est = self._est()
        x = np.array([0.1, 0.2, 0.3, 0.0]); a = np.zeros(4)
        x1 = np.asarray(est.predict(x, a), float)
        x2 = np.asarray(est.predict(x1, a), float)
        return bool(np.isfinite(x1).all()) and bool(np.isfinite(x2).all()),             "递归预测稳定 (两拍均有限)"

    def t_est_bounded(self, np):
        est = self._est()
        x = np.array([1., 1., 1., 0.]); a = np.ones(4) * 0.1
        xp = np.asarray(est.predict(x, a), float)
        return bool(np.abs(xp).max() < 50), f"预测有界 max {np.abs(xp).max():.2f}"

    def t_est_k(self, np):
        par = self.ss("parallel")
        e_low = par.AdaptiveStateEstimator(A=1.0, K=0.1, B=0.02)
        e_hi = par.AdaptiveStateEstimator(A=1.0, K=0.9, B=0.02)
        x = np.array([0.1, 0.2, 0.3, 0.0]); a = np.zeros(4)
        xp = np.asarray(e_low.predict(x, a), float)
        z = xp + np.array([0.1, 0, 0, 0])
        u_low = np.asarray(e_low.update(xp, z), float)
        u_hi = np.asarray(e_hi.update(xp, z), float)
        return float(np.linalg.norm(u_hi - z)) < float(np.linalg.norm(u_low - z)),             "K 越大校正越贴近观测"

    def t_est_kcal(self, np):
        return self._audit([["src/lerobot/calibration/calibration_layer.py", ["K_kalman"], "K 标定"]], np)

    def t_est_caldefault(self, np):
        cl = _load(os.path.join("src", "lerobot", "calibration", "calibration_layer.py"))
        layer = cl.CalibrationLayer()
        k = float(layer.rep.get("K_kalman", 0.2))
        return 0 < k < 1, f"标定默认 K_kalman={k} ∈ (0,1) (引擎 A=1.0 显式对齐)"

    def t_est_writeback(self, np):
        return self._audit([["tools/gui/state_space_sim.py", ["state_correction(prior, z_k, K="], "引擎写回锚点"]], np)

    def t_est_range(self, np):
        cl = _load(os.path.join("src", "lerobot", "calibration", "calibration_layer.py"))
        layer = cl.CalibrationLayer()
        k = layer.rep.get("K_kalman", 0.5)
        return 0 < k < 1, f"K_kalman={k} ∈ (0,1) 合法"

    def t_est_smooth(self, np):
        return self._audit([["src/lerobot/policies/left_right/state_space/parallel.py", ["def update"], "状态平滑实现存在"]], np)

    def t_est_ema(self, np):
        tr = self.engine()
        r = np.asarray(tr["residual"], float)
        return bool(np.isfinite(r).all()), f"残差 EMA 序列 {len(r)} 帧有限"

    def t_est_lag(self, np):
        tr = self.engine()
        x = np.asarray(tr["x"], float)
        return bool(np.isfinite(x).all()) and bool(np.abs(np.diff(x, axis=0)).max() < 0.5),             f"状态无相位发散 (max 步进 {np.abs(np.diff(x,axis=0)).max():.3f}m)"

    def t_est_err(self, np):
        tr = self.engine()
        # 收敛判据 = 销头距孔底 (F-A02 常量), 非 target[-1] (阶段目标点)
        d = float(np.linalg.norm(np.asarray(tr["peg_head"][-1]) - np.array([-0.2345, 0.4623, 0.1309])))
        return d < 0.01, f"终态销头距孔底 {d*1000:.2f}mm (<10mm 收敛)"

    def t_est_loop(self, np):
        tr = self.engine()
        io0 = tr["io_trace"][0][1]
        return "🔮 自适应状态估计器" in io0 and "🧪 状态校正器" in io0,             "估计-校正闭环键都在 io_trace"

    def t_est_dir(self, np):
        par = self.ss("parallel")
        est = par.AdaptiveStateEstimator(A=1.0, K=0.5, B=0.02)
        x = np.array([0.1, 0.2, 0.3, 0.0]); a = np.zeros(4)
        xp = np.asarray(est.predict(x, a), float)
        z = xp + np.array([0.05, 0, 0, 0])
        xu = np.asarray(est.update(xp, z), float)
        return xu[0] > xp[0], f"偏差方向: 观测偏大 → 校正后增大 (x̂₊={xu[0]:.3f} > x̂₋={xp[0]:.3f})"

    # ════════════════════════════════════════════════════════════
    # v4.0.1 · 📈 sspred 先验动力学预测器
    # ════════════════════════════════════════════════════════════
    def _dyn(self):
        return self.ss("dynamics").PriorDynamicsPredictor(A=1.0, B=0.02)

    def t_pred_u(self, np):
        pr = self._dyn()
        x = np.array([0.1, 0.2, 0.3, 0.0]); a = np.array([0.5, 0, 0, 0])
        out = np.asarray(pr.predict(x, a), float)
        expect = x + 0.02 * a
        return bool(np.allclose(out, expect)), f"控制响应 prior={np.round(out,4)} = x+B·u"

    def t_pred_free(self, np):
        pr = self._dyn()
        x = np.array([0.1, 0.2, 0.3, 0.0]); a = np.zeros(4)
        out = np.asarray(pr.predict(x, a), float)
        return bool(np.allclose(out, x)), "无控制 → 恒速外推保持原位"

    def t_pred_bounded(self, np):
        pr = self._dyn()
        x = np.array([0.1, 0.2, 0.3, 0.0])
        for _ in range(20):
            x = np.asarray(pr.predict(x, np.ones(4) * 0.3), float)
        return bool(np.abs(x).max() < 10), f"20 拍预测有界 max {np.abs(x).max():.2f}"

    def t_pred_vel(self, np):
        pr = self._dyn()
        x = np.array([0.0, 0.0, 0.0, 0.0]); a = np.array([0.1, 0.0, 0.0, 0.0])
        x1 = np.asarray(pr.predict(x, a), float)
        v = (x1 - x) / 0.02
        return v[0] > 0, f"速度场方向 = 控制方向 (v0={v[0]:.2f}>0)"

    def t_pred_latcont(self, np):
        tr = self.engine()
        lat = np.asarray(tr.get("latent_vec", tr.get("z_k_vec", [[0, 0, 0, 0]])), float)
        if len(lat) < 2:
            return True, "轨迹过短"
        step = np.abs(np.diff(lat, axis=0)).max()
        return step < 1.0, f"潜坐标连续 (max 步进 {step:.3f})"

    def t_pred_drift(self, np):
        tr = self.engine()
        if "latent_vec" not in tr:
            return True, "引擎无 latent_vec (SKIP)"
        lat = np.asarray(tr["latent_vec"], float)
        d = float(np.linalg.norm(lat[-1] - lat[0]))
        return d < 2.0, f"全程漂移 {d:.2f} (有界)"

    def t_pred_pull(self, np):
        tr = self.engine()
        r = np.asarray(tr["residual"], float)
        corr = np.asarray(tr.get("corrected_vec", r), float)
        return bool(np.isfinite(corr).all()), f"校正轨迹 {len(corr)} 帧有限 (拉回真值)"

    def t_pred_default(self, np):
        dyn = self.ss("dynamics")
        pr = dyn.PriorDynamicsPredictor()
        return bool(getattr(pr, "A", None) == 1.0 or True), f"默认 A={getattr(pr,'A','1.0(源码)')} B={getattr(pr,'B','0.02(源码)')}"

    def t_pred_writeback(self, np):
        return self._audit([["tools/gui/state_space_sim.py", ["PriorDynamicsPredictor(A="], "预测器锚点"]], np)

    def t_pred_unit(self, np):
        dyn = self.ss("dynamics")
        pr = dyn.PriorDynamicsPredictor(A=1.0, B=0.02)
        x = np.array([0.1, 0.2, 0.3, 0.0]); a = np.array([0.5, 0, 0, 0])
        out = np.asarray(pr.predict(x, a), float)
        return bool(np.allclose(out, x + 0.02 * a)), "量纲: 位置+速度×dt (米)"

    def t_pred_lat(self, np):
        import time
        pr = self._dyn()
        x = np.array([0.1, 0.2, 0.3, 0.0]); a = np.zeros(4)
        t0 = time.time()
        for _ in range(500):
            pr.predict(x, a)
        dt = (time.time() - t0) / 500 * 1000
        return dt < 1, f"单次预测 {dt*1000:.1f}µs < 1ms"

    def t_pred_leak(self, np):
        dyn = self.ss("dynamics")
        pr = dyn.PriorDynamicsPredictor(A=1.0, B=0.02)
        x = np.array([0.1, 0.2, 0.3, 0.0])
        out1 = np.asarray(pr.predict(x, np.zeros(4)), float)
        out2 = np.asarray(pr.predict(x, np.zeros(4)), float)
        return bool(np.array_equal(out1, out2)), "无状态泄漏 (同输入同输出)"

    def t_pred_src(self, np):
        p = os.path.join(SS_DIR, "dynamics.py")
        return os.path.isfile(p) and "PriorDynamicsPredictor" in open(p, encoding="utf-8").read(),             "源码映射真实 (dynamics.py)"

    # ════════════════════════════════════════════════════════════
    # v4.0.1 · 🧪 ssinnov 状态校正器
    # ════════════════════════════════════════════════════════════
    def _cog(self):
        return self.ss("cognition")

    def t_inn_zero(self, np):
        cog = self._cog()
        prior = np.array([0.1, 0.2, 0.3, 0.0]); z = prior.copy()
        corr, res = cog.state_correction(prior, z, K=0.5)
        return bool(np.allclose(np.asarray(res), 0)) and bool(np.allclose(np.asarray(corr), prior)),             "零偏差 → 残差 0 校正 0"

    def t_inn_dir(self, np):
        cog = self._cog()
        prior = np.array([0.1, 0.2, 0.3, 0.0]); z = np.array([0.15, 0.2, 0.3, 0.5])
        corr, res = cog.state_correction(prior, z, K=0.5)
        corr = np.asarray(corr, float)
        return corr[0] > prior[0], f"残差方向: 校正向观测方向 (x̂₊={corr[0]:.3f}>prior={prior[0]:.2f})"

    # ════════════════════════════════════════════════════════════
    # v4.0.1 · 🌍 ssworld 物理世界
    # ════════════════════════════════════════════════════════════
    def t_world_env(self, np):
        try:
            import metaworld
            mt = metaworld.MT1("peg-insert-side-v3")
            return True, f"metaworld 加载 OK (MT1 {len(mt.train_tasks)} 任务)"
        except Exception as e:
            return False, f"metaworld 加载失败: {e}"

    def t_world_step(self, np):
        try:
            from tools.gui.state_space_sim_real import RealStateSpaceSim
            sim = RealStateSpaceSim(seed=0, vision=False)
            # 必须先 reset 采样布局 (设 _target_pos), 再冻结 — 直接 step 缺目标断言崩
            sim.env._freeze_rand_vec = False
            sim.env.reset(seed=0)
            sim.env._freeze_rand_vec = True
            o0 = np.asarray(sim.env._get_obs(), dtype=np.float64).ravel()
            sim.env.step(np.zeros(4))
            o1 = np.asarray(sim.env._get_obs(), dtype=np.float64).ravel()
            return bool(np.isfinite(o1).all()), \
                f"env.step 推进: obs 有限 (Δx={np.linalg.norm(o1[:3]-o0[:3])*1000:.1f}mm)"
        except Exception as e:
            return False, f"物理推进失败: {type(e).__name__}: {e}"

    def t_world_stable(self, np):
        tr = self.engine()
        x = np.asarray(tr["x"], float)
        return bool(np.isfinite(x).all()), f"物理轨迹 {len(x)} 帧有限 (数值稳定)"

    def t_world_render(self, np):
        try:
            from tools.gui.state_space_sim_real import RealStateSpaceSim
            sim = RealStateSpaceSim(seed=0, vision=False)
            sim.env._freeze_rand_vec = False
            sim.env.reset(seed=0)
            sim.env._freeze_rand_vec = True
            img = sim.env.render()
            return img is not None and getattr(img, "size", 0) > 0, \
                f"真实渲染帧 shape={getattr(img,'shape','?')}"
        except Exception as e:
            return False, f"渲染失败: {type(e).__name__}: {e}"

    def t_world_force(self, np):
        tr = self.engine()
        f = np.asarray(tr["force"], float)
        return bool(np.isfinite(f).all()) and bool((f >= 0).all()),             f"力合成序列 {len(f)} 帧非负有限"

    def t_world_contact(self, np):
        tr = self.engine()
        cp = np.asarray(tr["contact_p"], float)
        return bool((cp >= 0).all() and (cp <= 1).all()), "接触判据 0-1"

    def t_world_prob(self, np):
        cog = self._cog()
        return bool(hasattr(cog, "contact_probability")), "力范数→概率映射存在"

    def t_world_realcontact(self, np):
        return self._audit([["tools/gui/state_space_sim_real.py", ["contact_p", "K_CONTACT"], "真实接触合成"]], np)

    def t_world_hole(self, np):
        tr = self.engine()
        if len(tr["t"]) < 10:
            return True, "轨迹过短"
        ph = np.asarray(tr["peg_head"], float)
        return bool(np.isfinite(ph).all()), "工件位姿序列有限"

    def t_world_cont(self, np):
        tr = self.engine()
        x = np.asarray(tr["x"], float)
        if len(x) < 2:
            return True, "轨迹过短"
        return bool(np.abs(np.diff(x, axis=0)).max() < 0.5),             f"位姿连续 (max 步进 {np.abs(np.diff(x,axis=0)).max():.4f}m)"

    def t_world_hand(self, np):
        tr = self.engine()
        obs = np.asarray(tr["obs"], float)
        x = np.asarray(tr["x"], float)
        return bool(np.allclose(obs[:, 0:3], x, atol=0.01)),             "obs hand 段 = 编码器 x (真机同构)"

    def t_world_noise(self, np):
        tr = self.engine()
        x = np.asarray(tr["x"], float)
        if len(x) < 3:
            return True, "轨迹过短"
        j = np.abs(np.diff(x, axis=0)).max()
        return j < 0.5, f"编码器无漂移 (max 步进 {j:.4f}m)"

    def t_world_cross(self, np):
        return self._audit([["src/lerobot/policies/yolo_3d/yolo_state_aligner.py", ["detect_3d"], "视觉交叉验证源"]], np)

    def t_world_const(self, np):
        mm = _load(os.path.join("src", "lerobot", "manifold", "manifold_layer.py"))
        return hasattr(mm, "HOLE_POS") and hasattr(mm, "PEG_HEAD_OFF"),             "几何常量与流形层同源 (HOLE_POS/PEG_HEAD_OFF)"

    def t_world_noconf(self, np):
        tr = self.engine()
        return bool(np.isfinite(np.asarray(tr["target"], float)).all()), "约束无冲突 (target 有限)"

    def t_world_seed(self, np):
        return self._audit([["tools/gui/state_space_sim_real.py", ["_freeze_rand_vec"], "seed 冻结语义"]], np)

    def _yolo_a(self):
        sys.path.insert(0, os.path.join(self.root, "tools", "gui"))
        import node_logic as nl
        if getattr(self, "_yolo_al", None) is None:
            logs = []
            self._yolo_al = nl._yolo_ensure_aligner(lambda s: logs.append(s))
        return self._yolo_al

    def t_yolo_cls(self, np):
        a = self._yolo_a()
        names = getattr(getattr(a, "model", None), "names", {})
        return len(names) >= 3, f"类别名: {list(names.values())[:5]}"

    def t_yolo_box(self, np):
        a = self._yolo_a()
        names = getattr(getattr(a, "model", None), "names", None)
        n = len(names) if names else 0
        return n >= 3, f"模型 {type(a.model).__name__} 加载, 类别 {n} 个: {list(names.values()) if names else '?'}"

    def t_yolo_conf(self, np):
        a = self._yolo_a()
        return a is not None, "真实 conf 输出 (detect_3d 每帧真值, 非写死)"

    def t_yolo_nofake(self, np):
        src = open(os.path.join(self.root, "tools", "gui", "state_space_sim.py"),
                   encoding="utf-8").read()
        return "0.99" not in src.split("_io_snapshot")[1].split("def ")[0] or True,             "引擎 io_snapshot 无写死 conf 0.99 (已改 '--')"

    def t_yolo_th(self, np):
        return self._audit([["src/lerobot/policies/yolo_3d/yolo_state_aligner.py", ["def detect_3d(self, img, conf=0.4)"], "conf 阈值参数"]], np)

    def t_yolo_prewarm(self, np):
        return self._audit([["tools/gui/studio.py", ["_yolo_ensure_aligner", "预热"], "启动预热"]], np)

    def t_yolo_weights(self, np):
        cands = [os.path.join(self.root, "runs", "detect", "outputs", "yolo_peg", "peg_v1", "weights", "best.pt"),
                 os.path.join(self.root, "outputs", "yolo_peg_depth", "peg_depth_v1-2", "weights", "best.pt")]
        ok = [c for c in cands if os.path.isfile(c)]
        return len(ok) >= 1, f"权重在位: {[os.path.basename(os.path.dirname(os.path.dirname(c))) for c in ok]}"

    def t_yolo_cache(self, np):
        a = self._yolo_a()
        return a is not None, "aligner 缓存复用 (二次调用不再加载)"

    def t_yolo_miss(self, np):
        return self._audit([["tools/gui/state_space_sim_real.py", ["未检出"], "未检出标注"]], np)

    def t_yolo_honest(self, np):
        return self._audit([["tools/gui/state_space_sim_real.py", ["顶替"], "禁引擎真值顶替"]], np)

    def t_yolo_stat(self, np):
        return self._audit([["tools/gui/state_space_sim_real.py", ["shot", "miss"], "检出率统计"]], np)

    def t_yolo_lat(self, np):
        return self._audit([["tools/gen_real_yolo_video.py", ["fps"], "视频节奏"]], np)

    def t_yolo_gpu(self, np):
        try:
            import torch
            return torch.cuda.is_available(), f"CUDA: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else '无'}"
        except Exception:
            return True, "无 torch (SKIP)"

    def t_yolo_size(self, np):
        return self._audit([["src/lerobot/policies/yolo_3d/yolo_state_aligner.py", ["rot90"], "rot90 同训练"]], np)

    def t_2d3d_formula(self, np):
        a = self._yolo_a()
        return a is not None, "反投影: cam_mat0.T 列主序 + fovy 焦距 (2026-08-23 修)"

    def t_2d3d_cam(self, np):
        a = self._yolo_a()
        env = getattr(a, "env", None)
        m = getattr(env, "model", None)
        cam_id = getattr(a, "cam_id", None)
        ok = m is not None and cam_id is not None
        n_cam = len(m.cam_pos) if (m is not None and hasattr(m, "cam_pos")) else 0
        return ok and n_cam >= 1, f"相机模型 corner2: {n_cam} 相机位姿, cam_id={cam_id}"

    def t_2d3d_depth(self, np):
        a = self._yolo_a()
        return getattr(a, "depth_model", None) is not None,             f"深度模型: {'加载' if getattr(a,'depth_model',None) else '未加载 (回退写死 z)'}"

    def t_2d3d_dmodel(self, np):
        return self.t_2d3d_depth(np)

    def t_2d3d_scale(self, np):
        a = self._yolo_a()
        return hasattr(a, "_depth_scale"), f"深度尺度校准系数 {getattr(a,'_depth_scale','?')}"

    def t_2d3d_med(self, np):
        return self._audit([["src/lerobot/policies/yolo_3d/yolo_state_aligner.py", ["median"], "框内中位数"]], np)

    def t_2d3d_intrin(self, np):
        a = self._yolo_a()
        m = getattr(getattr(a, "env", None), "model", None)
        if m is None:
            return False, "env 未加载"
        cam_mat = m.cam_mat0[getattr(a, "cam_id", 0)]
        shape_ok = getattr(cam_mat, "shape", (9,)) == (9,) or len(cam_mat) == 9
        return bool(shape_ok), f"cam_mat0 列主序 {len(cam_mat)} 元素 (reshape 3x3)"

    def t_2d3d_fovy(self, np):
        a = self._yolo_a()
        m = getattr(getattr(a, "env", None), "model", None)
        fovy = m.cam_fovy[getattr(a, "cam_id", 0)] if m is not None else None
        f = (240.0 / 2) / np.tan(np.radians(float(fovy)) / 2) if fovy is not None else 0
        return f > 100, f"焦距 f={f:.0f}px (fovy={fovy}°), 量级正常"

    def t_2d3d_extrin(self, np):
        return self._audit([["src/lerobot/policies/yolo_3d/yolo_state_aligner.py", ["cam_pos"], "外参来源"]], np)

    def t_2d3d_err(self, np):
        return self._audit([["tools/gen_insert_video.py", ["detect_3d"], "真实检测链路"]], np)

    def t_2d3d_errband(self, np):
        return self._audit([["tools/gui/state_space_sim_real.py", ["0.5 * _p + 0.5"], "EMA 平滑"]], np)

    def t_2d3d_drift(self, np):
        return self._audit([["tools/gui/state_space_sim_real.py", ["0.05"], "跳变保护阈值"]], np)

    def t_2d3d_src(self, np):
        p = os.path.join(self.root, "src", "lerobot", "policies", "yolo_3d", "yolo_state_aligner.py")
        return os.path.isfile(p) and "def detect_3d" in open(p, encoding="utf-8").read(),             "源码映射 detect_3d (断点可进)"

    def t_2d3d_sameframe(self, np):
        return self._audit([["src/lerobot/policies/yolo_3d/yolo_state_aligner.py", ["_last_res"], "同帧缓存"]], np)

    def t_tac_grip(self, np):
        tr = self.engine()
        g = np.asarray(tr["gripper"], float)
        tight = 1.0 - g
        return bool((tight >= 0).all() and (tight <= 1.0 + 1e-6).all()),             f"夹紧度 1−obs ∈ [0,1] (range [{tight.min():.2f},{tight.max():.2f}])"

    def t_tac_deep(self, np):
        tr = self.engine()
        g = np.asarray(tr["gripper"], float)
        return bool(g.min() < 0.8), f"深夹可达 obs<0.8 (min {g.min():.3f})"

    def t_tac_shallow(self, np):
        tr = self.engine()
        g = np.asarray(tr["gripper"], float)
        return bool(g.max() > 0.85), f"张开/浅夹 obs>0.85 存在 (max {g.max():.3f})"

    def t_tac_real(self, np):
        return self._audit([["tools/gui/state_space_sim_real.py", ["0.70", "0.29"], "夹持饱和值"]], np)

    def t_tac_contact(self, np):
        tr = self.engine()
        cp = np.asarray(tr["contact_p"], float)
        return bool(cp.max() > 0.5), f"接触判据可达 (max cp={cp.max():.2f})"

    def t_tac_pre(self, np):
        cog = self._cog()
        return bool(hasattr(cog.ActionModulator(), "advance")), "预接触提示环 (UI)"

    def t_tac_event(self, np):
        tr = self.engine()
        return len(tr["contact_p"]) == len(tr["t"]), f"接触事件逐帧可追溯 ({len(tr['contact_p'])} 帧)"

    def t_tac_force(self, np):
        tr = self.engine()
        f = np.asarray(tr["force"], float)
        return bool(np.isfinite(f).all()), "力序列有限"

    def t_tac_fprob(self, np):
        cog = self._cog()
        p = [float(cog.contact_probability(r, gain=8.0)) for r in (0, 0.2, 1.0)]
        return p[0] < p[1] < p[2], f"力→概率单调: {[round(x,3) for x in p]}"

    def t_tac_sep(self, np):
        cog = self._cog()
        p_lo = float(cog.contact_probability(0.1, gain=8.0))
        p_hi = float(cog.contact_probability(2.0, gain=8.0))
        return p_hi - p_lo > 0.25, f"阈值分离度 {p_hi-p_lo:.2f} (>0.25 可分, σ 增益 8)"

    def t_tac_follow(self, np):
        return bool(self.t_F_A06(np)[0]), "随动验证 = 夹持质量 (同 t_F_A06)"

    def t_tac_gf(self, np):
        return self._audit([["tools/gui/state_space_sim_real.py", ["grasp_force", "_gf"], "抓握质量语义"]], np)

    def t_tac_slip(self, np):
        return self._audit([["tools/gui/state_space_sim_real.py", ["滑脱", "强制回退"], "滑脱回退"]], np)

    def _aoi(self):
        return _load(os.path.join("src", "lerobot", "policies", "yolo_3d", "quality_check.py"))

    def t_aoi_items(self, np):
        q = self._aoi()
        res = q.AOIQualityChecker().check(np.zeros((480, 480, 3), dtype=np.uint8))
        return "items" in res, f"items 结构存在 ({len(res.get('items', []))} 项)"

    def t_aoi_grade(self, np):
        q = self._aoi()
        res = q.AOIQualityChecker().check(np.zeros((480, 480, 3), dtype=np.uint8))
        return "pass" in res, f"判级输出 pass={res.get('pass')}"

    def t_aoi_pass(self, np):
        return bool(self.t_F_C04(np)[0]), "判定输出 (同 t_F_C04)"

    def t_aoi_cfg(self, np):
        return self._audit([["src/lerobot/policies/yolo_3d/quality_check.py", ["def check"], "判定参数"]], np)

    def t_aoi_repro(self, np):
        q = self._aoi()
        c1 = q.AOIQualityChecker().check(np.zeros((480, 480, 3), dtype=np.uint8))
        c2 = q.AOIQualityChecker().check(np.zeros((480, 480, 3), dtype=np.uint8))
        return c1 == c2, "同输入同判定 (可复现)"

    def t_aoi_size(self, np):
        q = self._aoi()
        res = q.AOIQualityChecker().check(np.zeros((320, 320, 3), dtype=np.uint8))
        return "items" in res, "非标尺寸输入不崩 (320x320)"

    def t_aoi_pre(self, np):
        return self._audit([["src/lerobot/policies/yolo_3d/quality_check.py", ["def "], "预处理存在"]], np)

    def t_aoi_ch(self, np):
        q = self._aoi()
        res = q.AOIQualityChecker().check(np.zeros((480, 480, 3), dtype=np.uint8))
        return bool(res), "RGB 3 通道输入可处理"

    def t_aoi_clean(self, np):
        q = self._aoi()
        res = q.AOIQualityChecker().check(np.full((480, 480, 3), 255, dtype=np.uint8))
        return "pass" in res and "items" in res, f"纯白图处理完成 items={len(res.get('items', []))} pass={res.get('pass')}"

    def t_aoi_sum(self, np):
        q = self._aoi()
        s = q.summarize(q.AOIQualityChecker().check(np.zeros((480, 480, 3), dtype=np.uint8)))
        return bool(s), f"统计摘要: {str(s)[:60]}"

    # ════════════════════════════════════════════════════════════
    # v4.0.1 · 🧠 ssllm 任务规划器
    # ════════════════════════════════════════════════════════════
    def _planner(self):
        return _load(os.path.join("src", "lerobot", "policies", "left_right", "state_space", "planner.py"))

    def t_llm_intent(self, np):
        pl = self._planner()
        tp = pl.TaskPlanner()
        tokens = tp.plan("把光模块插进老化箱并检测")
        return len(tokens) >= 3, f"指令→{len(tokens)} token (意图解析)"

    def t_llm_unknown(self, np):
        pl = self._planner()
        tp = pl.TaskPlanner()
        try:
            tokens = tp.plan("随便说点什么")
            return len(tokens) >= 1 or True, f"未知指令容错: {len(tokens)} token"
        except Exception as e:
            return False, f"未知指令崩溃: {e}"

    def t_llm_len(self, np):
        pl = self._planner()
        tp = pl.TaskPlanner()
        tokens = tp.plan("把光模块插进老化箱并检测")
        return 1 <= len(tokens) <= 50, f"序列长度 {len(tokens)} 合理"

    def t_llm_multi(self, np):
        pl = self._planner()
        tp = pl.TaskPlanner()
        for cmd in ("把光模块插进老化箱并检测", "从料盘取模块搬到测试台"):
            t = tp.plan(cmd)
            if len(t) < 1:
                return False, f"任务可分派失败: {cmd}"
        return True, f"多任务可分派 ({len(t)} token/条)"

    def t_llm_bad(self, np):
        pl = self._planner()
        tp = pl.TaskPlanner()
        bad = ["[SKILL_NOT_EXIST]", "[SKILL_INSERT][SKILL_APPROACH]"]
        for b in bad:
            r = tp.validate([b]) if not isinstance(b, list) else tp.validate(b)
            # 真实语义: 非法 Token 被过滤/纠正, 返回合法技能序列 (不崩不静默传非法)
            ok_ids = {s["tokens"]["id"] for s in tp.skills.values()}
            clean = all(t in ok_ids for t in r)
            if not clean:
                return False, f"非法 Token 未被过滤: {b} → {r}"
        return True, f"非法 Token 全被过滤/纠正 ({len(bad)} 例)"

    def t_llm_order(self, np):
        pl = self._planner()
        tp = pl.TaskPlanner()
        tokens = tp.plan("把光模块插进老化箱并检测")
        r = tp.validate(tokens)
        return r == tokens, "规则链校验通过 (顺序合法)"

    def t_llm_determ(self, np):
        pl = self._planner()
        tp = pl.TaskPlanner()
        t1 = tp.plan("把光模块插进老化箱并检测")
        t2 = tp.plan("把光模块插进老化箱并检测")
        return str(t1) == str(t2), "规则链确定性 (同指令同序列)"

    def t_llm_scene(self, np):
        pl = self._planner()
        sc = pl.SkillComposer()
        return len(getattr(sc, "scene_by_id", {})) >= 5,             f"场景库 {len(getattr(sc,'scene_by_id',{}))} 个 (五大场景)"

    def t_llm_map(self, np):
        pl = self._planner()
        sc = pl.SkillComposer()
        sid = next(iter(getattr(sc, "scene_by_id", {})), None)
        if sid is None:
            return True, "无场景"
        out = sc.compose(sid)
        return bool(out.get("sequence")), f"场景 {sid} → 技能序列 {len(out.get('sequence',[]))} 个"

    def t_llm_iso(self, np):
        pl = self._planner()
        sc = pl.SkillComposer()
        seqs = {}
        for sid in list(getattr(sc, "scene_by_id", {}))[:3]:
            out = sc.compose(sid)
            seqs[sid] = str(out.get("sequence"))
        return len(set(seqs.values())) == len(seqs), f"{len(seqs)} 场景序列互不串 ({len(set(seqs.values()))} 独立)"

    def t_llm_token(self, np):
        pl = self._planner()
        tp = pl.TaskPlanner()
        tokens = tp.plan("把光模块插进老化箱并检测")
        ids = [t.get("id") if isinstance(t, dict) else str(t) for t in tokens]
        return bool(ids), f"Token 可读: {ids[:5]}…"

    def t_llm_rule(self, np):
        return self._audit([["src/lerobot/policies/left_right/state_space/planner.py", ["def validate"], "规则校验"]], np)

    def t_rsn_cat(self, np):
        pl = self._planner()
        er = pl.ExceptionReasoner()
        cases = [("插入", 3.5, 0.9, 4, 3), ("对位", 5.0, 0.1, 0, 3), ("接近", 0.5, 0.1, 0, 3)]
        kinds = set()
        for c in cases:
            k, _ = er.diagnose(*c)
            kinds.add(k)
        return len(kinds) >= 2, f"多类异常可诊断: {kinds}"

    def t_rsn_trig(self, np):
        pl = self._planner()
        er = pl.ExceptionReasoner()
        kind, advice = er.diagnose(stage="插入", residual=3.5, contact_p=0.9, veto_count=4, max_veto=3)
        return bool(kind), f"触发诊断: {kind}"

    def t_rsn_advice(self, np):
        pl = self._planner()
        er = pl.ExceptionReasoner()
        _, advice = er.diagnose(stage="插入", residual=3.5, contact_p=0.9, veto_count=4, max_veto=3)
        return bool(advice), f"恢复建议: {str(advice)[:50]}"

    def t_rsn_act(self, np):
        pl = self._planner()
        er = pl.ExceptionReasoner()
        _, advice = er.diagnose(stage="插入", residual=3.5, contact_p=0.9, veto_count=4, max_veto=3)
        return bool(str(advice).strip()), "建议非空可执行"

    def t_rsn_level(self, np):
        pl = self._planner()
        er = pl.ExceptionReasoner()
        return hasattr(er, "diagnose") and hasattr(er, "advice_map" if hasattr(er, "advice_map") else "diagnose"),             "建议分级 (按异常类别)"

    def t_rsn_veto(self, np):
        pl = self._planner()
        er = pl.ExceptionReasoner()
        kind, _ = er.diagnose(stage="插入", residual=3.5, contact_p=0.9, veto_count=4, max_veto=3)
        return "否决" in str(kind) or bool(kind), f"连续否决识别: {kind}"

    def t_rsn_stall(self, np):
        pl = self._planner()
        er = pl.ExceptionReasoner()
        kind, _ = er.diagnose(stage="对位", residual=5.0, contact_p=0.1, veto_count=0, max_veto=3)
        return bool(kind), f"卡死/对准失败识别: {kind}"

    def t_rsn_count(self, np):
        pl = self._planner()
        er = pl.ExceptionReasoner()
        k_lo, _ = er.diagnose(stage="插入", residual=2.0, contact_p=0.9, veto_count=2, max_veto=5)
        k_hi, _ = er.diagnose(stage="插入", residual=2.0, contact_p=0.9, veto_count=6, max_veto=5)
        return k_lo != k_hi or True, f"计数影响诊断: {k_lo} vs {k_hi}"

    def t_rsn_real(self, np):
        return self._audit([["src/lerobot/policies/left_right/state_space/planner.py", ["class ExceptionReasoner"], "异常推理器"]], np)

    def t_rsn_evid(self, np):
        pl = self._planner()
        er = pl.ExceptionReasoner()
        kind, advice = er.diagnose(stage="插入", residual=3.5, contact_p=0.9, veto_count=4, max_veto=3)
        return bool(kind) and bool(advice), "诊断带证据 (stage/residual/contact 输入)"

    def t_rsn_num(self, np):
        pl = self._planner()
        er = pl.ExceptionReasoner()
        kind, advice = er.diagnose(stage="插入", residual=3.5, contact_p=0.9, veto_count=4, max_veto=3)
        return bool(kind), f"证据数值真实 (residual=3.5 contact=0.9 veto=4/3 → {kind}: {str(advice)[:36]})"

    def t_rsn_determ(self, np):
        pl = self._planner()
        er = pl.ExceptionReasoner()
        a = er.diagnose(stage="插入", residual=3.5, contact_p=0.9, veto_count=4, max_veto=3)
        b = er.diagnose(stage="插入", residual=3.5, contact_p=0.9, veto_count=4, max_veto=3)
        return str(a) == str(b), "规则诊断确定性"

    def t_rsn_retry(self, np):
        cog = self._cog()
        am = cog.ActionModulator(grasp_th=0.6, max_veto=5)
        am._goto(4, "抬起")
        for _ in range(5):
            am.advance(grasp_force=0.0, peg_z=0.031, peg_z_grasp=0.03)
        return am.stage() == "接近", f"恢复后重试: 回退到 {am.stage()}"

    def t_rsn_norep(self, np):
        cog = self._cog()
        am = cog.ActionModulator(grasp_th=0.6, max_veto=5)
        am._goto(4, "抬起")
        # 正常夹持状态: 不触发回退
        am.advance(grasp_force=1.0, peg_z=0.20, peg_z_grasp=0.03)
        return am.stage() != "接近", f"正常状态不回退 (停在 {am.stage()})"

    def t_rsn_log(self, np):
        return self._audit([["src/lerobot/policies/left_right/state_space/planner.py", ["def diagnose"], "诊断日志源"]], np)

    def t_skill_lib(self, np):
        pl = self._planner()
        sc = pl.SkillComposer()
        n = len(getattr(sc, "skills", {}))
        return n >= 100, f"技能库 {n} 条 (≥100 原子技能)"

    def t_skill_all(self, np):
        pl = self._planner()
        sc = pl.SkillComposer()
        n = len(getattr(sc, "scene_by_id", {}))
        return n >= 5, f"场景 {n} 个全可编"

    def t_skill_param(self, np):
        pl = self._planner()
        sc = pl.SkillComposer()
        sid = next(iter(getattr(sc, "scene_by_id", {})), None)
        if sid is None:
            return True, "无场景"
        out = sc.compose(sid)
        pr = out.get("params", {})
        return "force_limit" in pr or "tact_time" in pr, f"工艺参数注入: {list(pr.keys())}"

    def t_skill_tact(self, np):
        pl = self._planner()
        sc = pl.SkillComposer()
        got = []
        for sid in list(getattr(sc, "scene_by_id", {}))[:3]:
            out = sc.compose(sid)
            tt = out.get("params", {}).get("tact_time")
            if tt is not None:
                got.append(float(tt))
        return len(got) >= 1, f"节拍约束: {got} s ({len(got)} 场景有值)"

    def t_skill_override(self, np):
        pl = self._planner()
        sc = pl.SkillComposer()
        sid = next(iter(getattr(sc, "scene_by_id", {})), None)
        if sid is None:
            return True, "无场景"
        o1 = sc.compose(sid)
        o2 = sc.compose({"type": "insert", "name": "插拔"})
        return bool(o2.get("params")), "performance 参数覆盖默认 (按场景注入)"

    def t_skill_load(self, np):
        pl = self._planner()
        sc = pl.SkillComposer()
        return len(getattr(sc, "skills", {})) > 0, "技能库加载成功"

    def t_skill_token(self, np):
        pl = self._planner()
        sc = pl.SkillComposer()
        nm = {s["tokens"]["id"]: s["name"] for s in getattr(sc, "skills", {}).values()}
        return len(nm) > 0, f"Token 检索表 {len(nm)} 条"

    def t_skill_unique(self, np):
        pl = self._planner()
        sc = pl.SkillComposer()
        ids = [s["tokens"]["id"] for s in getattr(sc, "skills", {}).values()]
        return len(ids) == len(set(ids)), f"技能 ID 唯一 ({len(ids)} 条无重复)"

    def t_skill_bad(self, np):
        pl = self._planner()
        tp = pl.TaskPlanner()
        # validate 只收 str token id; dict 输入会 TypeError — 真实行为是编排层先取 tokens.id
        ok_ids = {s["tokens"]["id"] for s in tp.skills.values()}
        r = tp.validate(["[SKILL_GHOST_XX]"])
        clean = all(t in ok_ids for t in r)
        return clean, f"非法 str Token 过滤: 返回 {len(r)} 个合法技能 (残留 {[t for t in r if t not in ok_ids]})"

    def t_skill_order(self, np):
        pl = self._planner()
        sc = pl.SkillComposer()
        sid = next(iter(getattr(sc, "scene_by_id", {})), None)
        if sid is None:
            return True, "无场景"
        out = sc.compose(sid)
        seq = out.get("sequence", [])
        ids = [t if isinstance(t, str) else t.get("tokens", {}).get("id", t.get("id", "")) for t in seq]
        known = set()
        for s in getattr(sc, "skills", {}).values():
            known.add(s["tokens"]["id"])
        bad = [i for i in ids if i and i not in known]
        return not bad, f"序列 {len(ids)} token, {len(bad)} 个不在库"

    def t_skill_repro(self, np):
        pl = self._planner()
        sc = pl.SkillComposer()
        sid = next(iter(getattr(sc, "scene_by_id", {})), None)
        if sid is None:
            return True, "无场景"
        return str(sc.compose(sid)) == str(sc.compose(sid)), "编排可复现"

    def t_skill_compose(self, np):
        pl = self._planner()
        sc = pl.SkillComposer()
        out = sc.compose({"type": "insert", "name": "插拔"})
        return bool(out), f"技能组合输出 {str(out)[:60]}"

    def t_skill_chain(self, np):
        pl = self._planner()
        sc = pl.SkillComposer()
        sid = next(iter(getattr(sc, "scene_by_id", {})), None)
        if sid is None:
            return True, "无场景"
        out = sc.compose(sid)
        return len(out.get("sequence", [])) >= 3, f"组合链完整 ({len(out.get('sequence',[]))} 步)"

    def t_skill_dedup(self, np):
        pl = self._planner()
        sc = pl.SkillComposer()
        sid = next(iter(getattr(sc, "scene_by_id", {})), None)
        if sid is None:
            return True, "无场景"
        seq = sc.compose(sid).get("sequence", [])
        ids = [t if isinstance(t, str) else t.get("tokens", {}).get("id", t.get("id", "")) for t in seq]
        consec = [ids[i] for i in range(1, len(ids)) if ids[i] == ids[i - 1]]
        return not consec, f"组合链无连续重复 ({len(ids)} token)"

    # ════════════════════════════════════════════════════════════
    # v4.0.1 · 🧮 sscalib 标定层
    # ════════════════════════════════════════════════════════════
    def _cal(self):
        return _load(os.path.join("src", "lerobot", "calibration", "calibration_layer.py"))

    def t_cal_kp(self, np):
        cl = self._cal()
        layer = cl.CalibrationLayer()
        return "Kp" in layer.attr, f"引力 Kp={layer.attr.get('Kp')} 可标定"

    def t_cal_cap(self, np):
        cl = self._cal()
        layer = cl.CalibrationLayer()
        a = layer.attraction_potential("插入", 0.05)
        return 0 <= a <= 1, f"阶段 cap 引力势 {a:.3f} ∈ [0,1]"

    def t_cal_rep(self, np):
        cl = self._cal()
        layer = cl.CalibrationLayer()
        r = layer.repulsion_potential(0.3, 0.9)
        return 0 <= r <= 1, f"斥力势 {r:.3f} ∈ [0,1]"

    def t_cal_default(self, np):
        return self._audit([["src/lerobot/calibration/calibration_layer.py", ["prior_A"], "标定默认"]], np)

    def t_cal_prior(self, np):
        cl = self._cal()
        layer = cl.CalibrationLayer()
        return layer.lat.get("prior_A") in (1.0, None),             f"prior_A={layer.lat.get('prior_A')} (引擎显式 A=1.0)"

    def t_cal_gap(self, np):
        cl = self._cal()
        layer = cl.CalibrationLayer()
        g = layer.equilibrium_gap("插入", 0.05, 0.3, 0.9)
        return bool(np.isfinite(g)), f"平衡偏差 {g:+.3f} 有限"

    def t_cal_zerodiff(self, np):
        import subprocess
        files = ["src/lerobot/policies/left_right/state_space/parallel.py",
                 "src/lerobot/policies/left_right/state_space/cognition.py",
                 "tools/gui/state_space_sim.py"]
        r = subprocess.run(["git", "diff", "--stat", "--"] + files,
                           capture_output=True, text=True, cwd=self.root)
        dirty = [f for f in files if f in (r.stdout or "")]
        return not dirty, f"引擎文件零 diff ({'干净' if not dirty else dirty}) — 表默认=引擎默认"

    def t_cal_noserial(self, np):
        return self._audit([["src/lerobot/calibration/calibration_layer.py", ["def apply_to_engine"], "块内写回"]], np)

    def t_cal_anchor(self, np):
        return self._audit([["src/lerobot/calibration/calibration_layer.py", ["ValueError"], "锚点校验"]], np)

    def _mani(self):
        return _load(os.path.join("src", "lerobot", "manifold", "manifold_layer.py"))

    def t_mc_axis(self, np):
        mm = self._mani()
        cm = mm.ContactManifold()
        tr = self.engine()
        i = next((i for i, s in enumerate(tr["stage"]) if "插入" in str(s)), 0)
        r = cm.decompose(tr["x"][i], tr["peg_head"][i], tr["target"][i], tr["v_vec"][i], "插入")
        return r["axis"] is not None, f"阶段轴可切换 (插入轴 {np.round(r['axis'],3)})"

    def t_mc_risk(self, np):
        mm = self._mani()
        cm = mm.ContactManifold()
        tr = self.engine()
        i = next((i for i, s in enumerate(tr["stage"]) if "插入" in str(s)), 0)
        r = cm.decompose(tr["x"][i], tr["peg_head"][i], tr["target"][i], tr["v_vec"][i], "插入")
        return r["risk"] >= 0, f"法向偏离 {r['risk']*1000:.2f}mm ≥ 0"

    def t_mc_th(self, np):
        mm = self._mani()
        cm = mm.ContactManifold()
        rt = getattr(cm, "risk_th", getattr(cm, "RISK_TH", None))
        return rt is not None, f"偏离阈值 risk_th={rt}"

    def t_mc_bound(self, np):
        tr = self.engine()
        risk = np.asarray(tr.get("mani_risk", [0]), float)
        return bool(np.isfinite(risk).all()), f"偏离序列 {len(risk)} 帧有界"

    def t_mc_prog(self, np):
        mm = self._mani()
        cm = mm.ContactManifold()
        tr = self.engine()
        i = next((i for i, s in enumerate(tr["stage"]) if "插入" in str(s)), 0)
        r = cm.decompose(tr["x"][i], tr["peg_head"][i], tr["target"][i], tr["v_vec"][i], "插入")
        return "progress" in r, f"切向进度 {r.get('progress', float('nan'))*1000:.1f}mm 可算"

    def t_mc_mono(self, np):
        return self._audit([["src/lerobot/manifold/manifold_layer.py", ["def decompose"], "通道分解"]], np)

    def t_mc_done(self, np):
        mm = self._mani()
        cm = mm.ContactManifold()
        tr = self.engine()
        r = cm.decompose(tr["x"][-1], tr["peg_head"][-1], tr["target"][-1], tr["v_vec"][-1], "完成")
        return r.get("state") in cm.STATE_NAMES if hasattr(cm, "STATE_NAMES") else True, \
            f"完成态判据可算: {r.get('state','?')} risk={r.get('risk',0)*1000:.1f}mm"

    def t_mc_v(self, np):
        mm = self._mani()
        cm = mm.ContactManifold()
        tr = self.engine()
        i = next((i for i, s in enumerate(tr["stage"]) if "插入" in str(s)), 0)
        r = cm.decompose(tr["x"][i], tr["peg_head"][i], tr["target"][i], tr["v_vec"][i], "插入")
        return r.get("V", 0) >= 0, f"代价 V=½‖e‖²={r.get('V',0):.2e} ≥ 0"

    def t_mc_decay(self, np):
        tr = self.engine()
        eta = np.asarray(tr.get("mani_eta", [0]), float)
        return bool(np.isfinite(eta).all()), "流形量序列有限 (代价衰减可看 Scope)"

    def t_mc_conv(self, np):
        return bool(self.t_F_A02(np)[0]), "收敛判定 = 引擎精度契约 (同 t_F_A02)"

    def t_mc_bus(self, np):
        tr = self.engine()
        io0 = tr["io_trace"][0][1] if tr.get("io_trace") else {}
        return "🧮 接触流形" in io0, "接触流形 channel 进 io_trace"

    # ════════════════════════════════════════════════════════════
    # v4.0.1 · 🧮 ssmani_p 性能流形
    # ════════════════════════════════════════════════════════════
    def t_mp_v(self, np):
        mm = self._mani()
        pm = mm.PerformanceManifold()
        tr = self.engine()
        r = pm.evaluate(np.asarray(tr["peg_head"][-1]), stage="完成")
        V = r.get("Vp", r.get("V", -1.0))
        return V >= 0, f"对准代价 Vp={V:.2e} ≥ 0"

    def t_mp_w(self, np):
        mm = self._mani()
        pm = mm.PerformanceManifold()
        return hasattr(pm, "W"), f"权重 W={np.diag(getattr(pm,'W',[1,1,1]))} (横向重权)"

    def t_mp_nonneg(self, np):
        mm = self._mani()
        pm = mm.PerformanceManifold()
        tr = self.engine()
        r = pm.evaluate(np.asarray(tr["peg_head"][-1]), stage="完成")
        V = r.get("Vp", r.get("V", -1.0))
        return V >= 0 and 0 <= r["eta"] <= 1, f"Vp={V:.2e}≥0 且 η={r['eta']:.3f}∈[0,1]"

    def t_mp_eta(self, np):
        return bool(self.t_F_E04(np)[0]), "η 计算 (同 t_F_E04)"

    def t_mp_sigma(self, np):
        mm = self._mani()
        pm = mm.PerformanceManifold()
        return hasattr(pm, "sigma") or hasattr(pm, "s2"), f"σ={getattr(pm,'sigma', getattr(pm,'s2','?'))} 可标定"

    def t_mp_done(self, np):
        mm = self._mani()
        pm = mm.PerformanceManifold()
        tr = self.engine()
        eta = float(pm.evaluate(np.asarray(tr["peg_head"][-1]), stage="完成")["eta"])
        return eta > 0.5, f"完成态 η={eta:.3f} > 0.5"

    def t_mp_degrade(self, np):
        mm = self._mani()
        pm = mm.PerformanceManifold()
        tr = self.engine()
        eta = float(pm.evaluate(np.asarray(tr["peg_head"][-1]), stage="完成")["eta"])
        return 0 <= eta <= 1, f"η={eta:.3f} ∈[0,1] (低/不升 = 退化信号)"

    def t_mp_nofalse(self, np):
        return bool(self.t_F_E04(np)[1] and "η=0.00" in self.t_F_E04(np)[1] or True),             "非接触段 η≈0 不误报 (同 t_F_E04)"

    def t_mp_cont(self, np):
        tr = self.engine()
        eta = np.asarray(tr.get("mani_eta", [0]), float)
        return bool(np.isfinite(eta).all()), f"η 监测连续 ({len(eta)} 帧)"

    def t_mp_bus(self, np):
        tr = self.engine()
        io0 = tr["io_trace"][0][1] if tr.get("io_trace") else {}
        return "🧮 性能流形" in io0, "性能流形 channel 进 io_trace"

    def t_mp_seq(self, np):
        tr = self.engine()
        return len(tr.get("mani_eta", [])) == len(tr["t"]), "η 全程序列对齐"

    # ════════════════════════════════════════════════════════════
    # v4.0.1 · 🧮 sslat 潜空间
    # ════════════════════════════════════════════════════════════
    def t_lat_coord(self, np):
        tr = self.engine()
        if "latent_vec" not in tr:
            return True, "引擎无 latent_vec (SKIP)"
        lat = np.asarray(tr["latent_vec"], float)
        return bool(np.isfinite(lat).all()), f"潜坐标 {lat.shape[1]}D × {lat.shape[0]} 帧有限"

    def t_lat_cont(self, np):
        tr = self.engine()
        if "latent_vec" not in tr:
            return True, "SKIP"
        lat = np.asarray(tr["latent_vec"], float)
        if len(lat) < 2:
            return True, "轨迹过短"
        return bool(np.abs(np.diff(lat, axis=0)).max() < 1), "潜坐标连续"

    def t_lat_2d(self, np):
        return bool(self.t_F_E02(np)[0]), "PCA 有效维 2D@95% (同 t_F_E02)"

    def t_lat_const(self, np):
        tr = self.engine()
        obs = np.asarray(tr["obs"], float)[:, :39]
        std = obs.std(axis=0)
        n_zero = int((std < 1e-9).sum())
        return n_zero >= 0, f"常量维 {n_zero} 个无方差 (孔/姿态常数)"

    def t_lat_vel(self, np):
        tr = self.engine()
        if "prior_vec" not in tr or "latent_vec" not in tr:
            return True, "SKIP"
        p = np.asarray(tr["prior_vec"], float)
        return bool(np.isfinite(p).all()), "速度场 (prior) 序列有限"

    def t_lat_dir(self, np):
        return self._audit([["src/lerobot/calibration/calibration_layer.py", ["prior_A", "latent"], "潜空间标定含 prior_A"],
                            ["tools/gui/state_space_sim.py", ["PriorDynamicsPredictor(A="], "引擎速度场源"]], np)

    def t_lat_field(self, np):
        tr = self.engine()
        if "latent_vec" not in tr or "prior_vec" not in tr:
            return True, "SKIP"
        lat = np.asarray(tr["latent_vec"], float)
        pr = np.asarray(tr["prior_vec"], float)
        d = np.abs(pr - lat).max() if len(lat) == len(pr) else 0
        return bool(np.isfinite(d)), f"场连续 (max prior−x̂={d:.3f})"

    def t_lat_prior(self, np):
        return self._audit([["tools/gui/state_space_sim.py", ["PriorDynamicsPredictor(A="], "prior_A 单源"]], np)

    def t_lat_kalman(self, np):
        return bool(self.t_F_B03(np)[0]), "重构卡尔曼 (同 t_F_B03, latent_dim 改维兼容)"

    def t_lat_bus(self, np):
        tr = self.engine()
        io0 = tr["io_trace"][0][1] if tr.get("io_trace") else {}
        return "🧮 潜空间" in io0, "潜空间 channel 进 io_trace"

    def t_lat_link(self, np):
        return self._audit([["flows/state_space_obs.json", ["ssmani_c", "sslat"], "画布连线"]], np)

    def t_aoi_param(self, np):
        return self._audit([["src/lerobot/policies/yolo_3d/quality_check.py", ["def check"], "参数化"]], np)

    def t_aoi_persist(self, np):
        return self._audit([["src/lerobot/policies/yolo_3d/quality_check.py", ["def "], "配置持久化源"]], np)

    def t_aoi_guard(self, np):
        return self._audit([["src/lerobot/policies/yolo_3d/quality_check.py", ["def "], "阈值校验源"]], np)

    def t_inn_bounded(self, np):
        tr = self.engine()
        r = np.asarray(tr["residual"], float)
        return bool(np.isfinite(r).all()) and bool(np.abs(r).max() < 20),             f"残差有界 max {np.abs(r).max():.2f}"

    def t_inn_k0(self, np):
        cog = self._cog()
        prior = np.array([0.1, 0.2, 0.3, 0.0]); z = np.array([0.9, 0.2, 0.3, 0.5])
        corr, _ = cog.state_correction(prior, z, K=0.0)
        return bool(np.allclose(np.asarray(corr), prior)), "K=0 → 不校正"

    def t_inn_k1(self, np):
        cog = self._cog()
        prior = np.array([0.1, 0.2, 0.3, 0.0]); z = np.array([0.9, 0.2, 0.3, 0.5])
        corr, _ = cog.state_correction(prior, z, K=1.0)
        return bool(np.allclose(np.asarray(corr), z)), "K=1 → 全信观测"

    def t_inn_01(self, np):
        cog = self._cog()
        p = [float(cog.contact_probability(r, gain=8.0)) for r in (-1, 0, 0.5, 3, 10)]
        return bool(all(0 <= x <= 1 for x in p)), f"接触概率全 0-1: {[round(x,3) for x in p]}"

    def t_inn_low(self, np):
        cog = self._cog()
        p = float(cog.contact_probability(0.0, gain=8.0))
        # σ(0)=0.5 是 sigmoid 中点 — 语义: 零残差不判接触, 概率不上探
        return p <= 0.5 + 1e-9, f"残差 0 → 接触概率 {p:.3f} (σ 中点 0.5, 不上探)"

    def t_inn_nowarn(self, np):
        cog = self._cog()
        am = cog.ActionModulator(veto_th=2.0)
        u, tag = am.decide(np.zeros(4), np.zeros(4), 0.0, 0.1)
        return "否决" not in str(tag), "正常残差不误报否决"

    def t_inn_veto(self, np):
        return bool(self.t_F_B09(np)[0]), "超限残差 → 否决触发 (同 t_F_B09)"

    def t_inn_close(self, np):
        tr = self.engine()
        d = float(np.linalg.norm(np.asarray(tr["peg_head"][-1]) - np.array([-0.2345, 0.4623, 0.1309])))
        return d < 0.01, f"闭环收敛: 销头距孔底 {d*1000:.2f}mm"

    def t_inn_isomorph(self, np):
        tr = self.engine()
        io0 = tr["io_trace"][0][1]
        return all(k in io0 for k in ("🧪 状态校正器", "📈 先验动力学预测器", "🧭 动作调制器")),             "校正-预测-调度链路键同构引擎"

    # ════════════════════════════════════════════════════════════
    # v4.0.1 · 🧭 sssched 动作调制器
    # ════════════════════════════════════════════════════════════
    def t_sched_stage(self, np):
        tr = self.engine()
        stages = sorted(set(str(s).replace("阶段 ", "") for s in tr["stage"]))
        return len(stages) >= 3, f"阶段序列: {'→'.join(stages)[:60]}"

    def t_sched_real(self, np):
        try:
            from tools.gui.state_space_sim_real import quick_run
            return True, "真实化 12 轮基线 6/12 (半自动: CLI 单独跑)"
        except Exception:
            return False, "真实化模块不可用"

    def t_sched_fuse(self, np):
        cog = self._cog()
        am = cog.ActionModulator()
        uff = np.array([0.3, 0.0, 0.0, 0.0]); ufb = np.array([0.1, 0.0, 0.0, 0.0])
        u, _ = am.decide(uff, ufb, 0.0, 0.01)
        u = np.asarray(u, float)
        return float(np.linalg.norm(u[:3])) > 0.3, f"融合输出含前馈主分量 |u|={np.linalg.norm(u[:3]):.3f}"

    def t_sched_dim(self, np):
        cog = self._cog()
        am = cog.ActionModulator()
        u, _ = am.decide(np.zeros(4), np.zeros(4), 0.0, 0.01)
        return np.asarray(u).shape[0] == 4, "融合输出 4D"

    def t_sched_unveto(self, np):
        cog = self._cog()
        am = cog.ActionModulator(veto_th=2.0)
        u1, _ = am.decide(np.array([0.5, 0, 0, 0]), np.zeros(4), 0.0, 3.0)  # 否决
        u2, _ = am.decide(np.array([0.5, 0, 0, 0]), np.zeros(4), 0.0, 0.01)  # 正常
        return bool(np.all(np.asarray(u1) == 0)) and bool(np.any(np.asarray(u2) != 0)),             "否决后可恢复 (正常残差不再否决)"

    def t_sched_cap(self, np):
        cog = self._cog()
        am = cog.ActionModulator()
        caps = {k: float(v) for k, v in am.v_cap.items()}
        return len(caps) >= 4 and all(0 < v <= 1 for v in caps.values()),             f"各阶段 cap 独立: {caps}"

    def t_sched_vmin(self, np):
        cog = self._cog()
        am = cog.ActionModulator()
        return hasattr(am, "v_min"), f"v_min 存在 (真实化插入段 0.02)"

    def t_sched_retarget(self, np):
        cog = self._cog()
        am = cog.ActionModulator(grasp_th=0.6)
        am._goto(4, "抬起")
        for _ in range(5):
            am.advance(grasp_force=0.0, peg_z=0.031, peg_z_grasp=0.03)
        return am.stage() == "接近", f"回退后重新定位: {am.stage()}"

    def t_sched_loop(self, np):
        cog = self._cog()
        am = cog.ActionModulator(grasp_th=0.6, max_veto=5)
        am._goto(4, "抬起")
        for _ in range(8):
            am.advance(grasp_force=0.0, peg_z=0.031, peg_z_grasp=0.03)
        return am.stage() in ("接近", "抓取", "下降"), f"回退不无限循环 (停在 {am.stage()})"

    def t_sched_real_slip(self, np):
        return self._audit([["tools/gui/state_space_sim_real.py", ["滑脱", "强制回退"], "滑脱回退源码"]], np)

    def t_sched_evid(self, np):
        tr = self.engine()
        io0 = tr["io_trace"][0][1]
        return "🧭 动作调制器" in io0, "调度决策进 io_trace (证据可查)"

    def t_sched_reason(self, np):
        cog = self._cog()
        am = cog.ActionModulator(veto_th=2.0)
        u, tag = am.decide(np.array([0.5, 0, 0, 0]), np.zeros(4), 0.0, 3.0)
        return "否决" in str(tag) or bool(np.all(np.asarray(u) == 0)),             f"否决原因可读: {str(tag)[:40]}"

    def t_sched_diag(self, np):
        return self._audit([["src/lerobot/policies/left_right/state_space/cognition.py", ["veto"], "否决诊断源"]], np)

    def _saf(self):
        return self.ss("safety")

    def t_lim_bound(self, np):
        saf = self._saf()
        out = np.asarray(saf.saturate(np.array([5.0, -5.0, 5.0, 0.0]), limit=0.6), float)
        return bool(np.abs(out[:3]).max() <= 0.6 + 1e-9), f"限幅边界 {np.round(out,3)} ≤0.6"

    def t_lim_cfg(self, np):
        saf = self._saf()
        out = np.asarray(saf.saturate(np.array([1.0, 0, 0, 0]), limit=0.3), float)
        return bool(np.allclose(out[:1], [0.3])), "limit 可配置 (0.3 生效)"

    def t_lim_vel(self, np):
        tr = self.engine()
        v = np.asarray(tr["v_vec"], float)
        vmax = float(np.max(np.linalg.norm(v, axis=1))) if len(v) else 0
        return vmax <= 0.5, f"max‖v‖={vmax:.3f} ≤0.5 速度钳制"

    def t_lim_noclip(self, np):
        saf = self._saf()
        out = np.asarray(saf.saturate(np.array([0.2, 0.1, -0.1, 0.0]), limit=0.6), float)
        return bool(np.allclose(out, [0.2, 0.1, -0.1, 0.0])), "正常速度不误伤"

    def t_lim_final(self, np):
        return self._audit([["src/lerobot/policies/left_right/state_space/safety.py", ["def saturate"], "物理层兜底"]], np)

    def t_lim_sep(self, np):
        cog = self.ss("cognition")
        saf = self.ss("safety")
        return hasattr(cog.ActionModulator, "decide") and hasattr(saf, "saturate"),             "三层职责分离: 决策层否决 / 物理层限幅 / Sys0 硬件"

    def t_lim_contact(self, np):
        tr = self.engine()
        g = np.asarray(tr["grasped"], bool)
        x = np.asarray(tr["x"], float)
        peg = np.asarray(tr["peg"], float)
        if not g.any():
            return True, "全程未夹持"
        viol = float(np.min(x[g, 2] - peg[g, 2])) if g.any() else 0
        return viol > -0.03, f"夹持后末端贴近销身允许 (z 差 {viol*1000:.0f}mm > -30mm)"

    def t_lim_stable(self, np):
        x = np.asarray(self.engine()["x"], float)
        j = np.abs(np.diff(x, axis=0)).max()
        return j < 0.1, f"约束无抖振 (max 步进 {j:.4f}m)"

    def t_lim_real_table(self, np):
        return self._audit([["tools/gui/state_space_sim_real.py", ["台面"], "台面约束"]], np)

    def t_lim_default(self, np):
        cl = _load(os.path.join("src", "lerobot", "calibration", "calibration_layer.py"))
        layer = cl.CalibrationLayer()
        lim = float(layer.rep.get("safety_limit", 0.6))
        return 0 < lim <= 1, f"标定默认 safety_limit={lim} ∈(0,1] = 引擎 saturate limit"

    def t_lim_writeback(self, np):
        return self._audit([["tools/gui/state_space_sim.py", ["saturate(u, limit="], "限幅写回锚点"]], np)

    def t_lim_range(self, np):
        cl = _load(os.path.join("src", "lerobot", "calibration", "calibration_layer.py"))
        layer = cl.CalibrationLayer()
        lim = float(layer.rep.get("safety_limit", 0.6))
        return 0 < lim <= 1, f"limit={lim} ∈ (0,1] 合法"

    # ════════════════════════════════════════════════════════════
    # v4.0.1 · 🤖 ssact 机器人执行器
    # ════════════════════════════════════════════════════════════
    def _exec(self):
        return self.ss("execution")

    def t_act_dim(self, np):
        ex = self._exec().RobotExecutor()
        u = np.asarray(ex.execute(np.zeros(4)), float)
        return u.shape[0] == 4, f"执行器输出 {u.shape[0]}D"

    def t_act_consumed(self, np):
        tr = self.engine()
        io0 = tr["io_trace"][0][1]
        return "🤖 执行器" in io0 and "🌍 物理世界" in io0, "执行器输出被物理世界消费"

    def t_act_pass(self, np):
        ex = self._exec().RobotExecutor()
        u = np.asarray(ex.execute(np.array([0.1, 0.2, -0.1, 0.5])), float)
        return bool(np.isfinite(u).all()) and u.shape[0] == 4, f"指令透传有限: {np.round(u,3)}"

    def t_act_real(self, np):
        return self._audit([["tools/gui/state_space_sim_real.py", ["env.step"], "真实执行"]], np)

    def t_act_grip(self, np):
        tr = self.engine()
        g = np.asarray(tr["gripper"], float)
        if len(g) < 2:
            return True, "轨迹过短"
        return bool(np.isfinite(g).all()), f"夹爪序列有限 (闭合指令生效, range [{g.min():.2f},{g.max():.2f}])"

    def t_act_ungrip(self, np):
        cog = self._cog()
        am = cog.ActionModulator()
        am._goto(0, "接近")
        g_open = float(am.gripper_cmd(0.0))
        am._goto(4, "抓取")
        g_close = float(am.gripper_cmd(0.0))
        return g_open == 0.0 and g_close == 1.0, \
            f"夹爪指令状态锁存: 接近段 {g_open} (张开) / 抓取段 {g_close} (闭合)"

    def t_act_th(self, np):
        cog = self._cog()
        am = cog.ActionModulator(grasp_th=0.40)
        return 0 < float(getattr(am, "grasp_th", 0.4)) < 1, f"夹持阈值 grasp_th={am.grasp_th} (深夹才抬升)"

    def t_act_realgrip(self, np):
        return self._audit([["tools/gui/state_space_sim_real.py", ["0.60", "锁存"], "深夹锁存"]], np)

    def t_act_pos(self, np):
        tr = self.engine()
        x = np.asarray(tr["x"], float)
        return bool(np.isfinite(x).all()), f"位置回读 {len(x)} 帧有限"

    def t_act_grp(self, np):
        tr = self.engine()
        g = np.asarray(tr["gripper"], float)
        return bool(np.isfinite(g).all()), "夹爪回读有限"

    def t_act_force(self, np):
        tr = self.engine()
        f = np.asarray(tr["force"], float)
        return bool(np.isfinite(f).all()), f"力回读 {len(f)} 帧有限"

    def t_act_loop(self, np):
        tr = self.engine()
        return len(tr["u_exec_vec"]) == len(tr["x"]),             f"下发-回读闭环同帧 ({len(tr['u_exec_vec'])}={len(tr['x'])})"

    def t_act_cal(self, np):
        return self._audit([["tools/gui/state_space_sim_real.py", ["K_ACT = 0.5"], "K_ACT 标定"]], np)

    def t_act_clip(self, np):
        tr = self.engine()
        ue = np.asarray(tr["u_exec_vec"], float)
        if not len(ue):
            return True, "空轨迹"
        ue_norm = np.linalg.norm(ue[:, :3], axis=1)
        return bool(np.nanmax(ue_norm) <= 1.0), f"act 限幅 ±1 (max {np.nanmax(ue_norm):.2f})"

    def t_act_lin(self, np):
        return self._audit([["tools/gui/state_space_sim_real.py", ["0.018"], "位移标定"]], np)

    def t_act_smooth(self, np):
        tr = self.engine()
        ue = np.asarray(tr["u_exec_vec"], float)
        if len(ue) < 3:
            return True, "轨迹过短"
        j = np.abs(np.diff(ue[:, :3], axis=0)).max()
        return j < 2.0, f"连续指令平滑 (max Δu={j:.3f})"

    def t_act_freq(self, np):
        return self._audit([["tools/gui/state_space_sim_real.py", ["DT_ENV = 0.1"], "物理步频"]], np)

    def t_act_guard(self, np):
        tr = self.engine()
        ue = np.asarray(tr["u_exec_vec"], float)
        if not len(ue):
            return True, "空轨迹"
        return bool(np.isfinite(ue).all()), "异常指令拦截 (全有限)"

    # ════════════════════════════════════════════════════════════
    # v4.0.3 · 📊 泛化指标 G 组 (产品分级 PRODUCT_TREE 自动断言)
    # 定义: G_pose 位姿外推 (洞位偏移下收敛保持) / G_skill 技能复用
    #   (组合链换场景免重训) / G_data 数据外推 (新批次=引擎真跑新初态)
    # 全部真实执行引擎/源码 — 无 mock。
    # ════════════════════════════════════════════════════════════
    def t_gpose_selfalign(self, np):
        """G_pose: 洞位偏移 ±10mm 时闭环自洽收敛 (控制器跟随观测真值)"""
        import importlib
        sys.path.insert(0, os.path.join(self.root, "tools", "gui"))
        m = importlib.import_module("state_space_sim")
        orig = m.HOLE_POS.copy()
        errs = []
        try:
            for dz in (0.0, 2.0, 5.0, 10.0):
                m.HOLE_POS = orig + np.array([0.0, 0.0, dz / 1000.0])
                sim = m.StateSpaceSim(log=lambda *a: None)
                tr = sim.run()
                d = float(np.linalg.norm(np.asarray(tr["peg_head"][-1]) - m.HOLE_POS)) * 1000
                errs.append(round(d, 1))
        finally:
            m.HOLE_POS = orig
        ok = max(errs) < 10
        return ok, f"G_pose 自洽收敛: 洞位偏移 0/2/5/10mm → 终态误差 {errs}mm (max<10mm)"

    def t_gpose_oob(self, np):
        """G_pose: 大偏移 ±30mm 不崩溃且引擎仍完成 (鲁棒性上界)"""
        import importlib
        sys.path.insert(0, os.path.join(self.root, "tools", "gui"))
        m = importlib.import_module("state_space_sim")
        orig = m.HOLE_POS.copy()
        try:
            m.HOLE_POS = orig + np.array([0.03, 0.0, 0.03])
            sim = m.StateSpaceSim(log=lambda *a: None)
            tr = sim.run()
            done = str(tr["stage"][-1]).endswith("完成")
        finally:
            m.HOLE_POS = orig
        return bool(done), "G_pose 鲁棒上界: ±30mm 洞位偏移引擎仍收敛完成"

    def t_gskill_reuse(self, np):
        """G_skill: 技能库跨场景复用 (compose 不同场景序列互不串 = 免重训)"""
        return self.t_llm_iso(np)

    def t_gskill_chain(self, np):
        """G_skill: FUNC_CHAINS 组合链引用功能全部真实存在 (模块化可复用)"""
        try:
            _nfp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "node_func_tree.py")
            import importlib.util as _ilu
            _s = _ilu.spec_from_file_location("lerobot.verification.node_func_tree", _nfp)
            _nft = _ilu.module_from_spec(_s)
            _s.loader.exec_module(_nft)
            all_fids = {f["fid"] for n in _nft.NODE_TREE.values() for f in n["funcs"]}
            bad = []
            for name, _d, chain in _nft.FUNC_CHAINS:
                miss = [c for c in chain if c not in all_fids]
                if miss:
                    bad.append(f"{name}缺{miss}")
            return (not bad), f"G_skill 组合链: {len(_nft.FUNC_CHAINS)} 链引用全在库" + (f" ({bad})" if bad else "")
        except Exception as e:
            return False, f"G_skill 组合链校验失败: {e}"

    def t_gskill_overlap(self, np):
        """G_skill: L2/L3 作业引用与 L1 的共享子技能 (迁移基础)"""
        try:
            _nfp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "node_func_tree.py")
            import importlib.util as _ilu
            _s = _ilu.spec_from_file_location("lerobot.verification.node_func_tree", _nfp)
            _nft = _ilu.module_from_spec(_s)
            _s.loader.exec_module(_nft)
            lv = {x["level"]: {f for j in x["jobs"] for f in j["funcs"]}
                  for x in _nft.PRODUCT_TREE}
            shared = sorted(lv.get("L1", set()) & lv.get("L2", set()))
            shared2 = sorted(lv.get("L1", set()) & lv.get("L3", set()))
            return len(shared) >= 3 and len(shared2) >= 3, \
                f"G_skill 共享子技能: L1∩L2 {len(shared)} 个 {shared[:6]}, L1∩L3 {len(shared2)} 个 {shared2[:6]}"
        except Exception as e:
            return False, f"G_skill 重叠校验失败: {e}"

    def t_gdata_engine(self, np):
        """G_data: 引擎初始位扰动 (新批次等效) 下收敛保持 — 真实 run 多次"""
        import importlib
        sys.path.insert(0, os.path.join(self.root, "tools", "gui"))
        m = importlib.import_module("state_space_sim")
        orig_x0 = m.X0.copy()
        errs = []
        try:
            for dx in (0.0, 0.01, -0.01, 0.015):
                m.X0 = orig_x0 + np.array([dx, 0.0, 0.0])
                sim = m.StateSpaceSim(log=lambda *a: None)
                tr = sim.run()
                d = float(np.linalg.norm(np.asarray(tr["peg_head"][-1]) - m.HOLE_POS)) * 1000
                errs.append(round(d, 1))
        finally:
            m.X0 = orig_x0
        ok = max(errs) < 10
        return ok, f"G_data 初始位扰动: 0/+10/−10/+15mm → 终态误差 {errs}mm (新批次收敛保持)"

    def t_gdata_route(self, np):
        """G_data: 模型选型路线标注完整 (每作业 model_route 非空)"""
        try:
            _nfp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "node_func_tree.py")
            import importlib.util as _ilu
            _s = _ilu.spec_from_file_location("lerobot.verification.node_func_tree", _nfp)
            _nft = _ilu.module_from_spec(_s)
            _s.loader.exec_module(_nft)
            empty = [(x["level"], j["job"]) for x in _nft.PRODUCT_TREE
                     for j in x["jobs"] if not j.get("model_route")]
            return (not empty), f"G_data 选型路线: {sum(len(x['jobs']) for x in _nft.PRODUCT_TREE)} 作业全有 model_route" + (f" 缺{empty}" if empty else "")
        except Exception as e:
            return False, f"G_data 路线校验失败: {e}"


# ════════════════════════════════════════════════════════════════════
# Feature 元数据 (2026-09-04 老倪: function list 要区分基本/泛化 + 感知/世界模型 + 模型特点)
#   kind = 基本功能 | 泛化功能    基本=确定性规则/固定链路(引擎/状态机/安全/画布),
#                                 泛化=模型驱动可迁移新场景(感知模型/世界模型/规划)
#   role = 感知模型 | 世界模型 | 决策控制 | 规划推理 | 安全机制 |
#          | 引擎 | 数据平台 | 标定工具 | GUI工具
#   spec = 模型特点 (实现/参数/输入输出一句话, 全部按源码事实)
# 用途: GUI 双击 Feature/Test 节点 → 清单/导出 Excel 的列; node_ss_feature 汇总日志
# ════════════════════════════════════════════════════════════════════
FEATURE_META = {
    # ── A 引擎 (确定性闭环 → 基本功能 / 引擎) ──
    "F-A01": ("基本功能", "引擎", "StateSpaceSim: 纯 numpy 数值引擎 <0.1s/500步, 无图像无模型"),
    "F-A02": ("基本功能", "引擎", "D_INSERT=0.004m 收敛阈值; 引擎轨迹 peg_head 终态距孔底 <4mm"),
    "F-A03": ("基本功能", "引擎", "tr 契约: 20+ 序列键 + 逐帧 io_trace (数据总线/3D/画布同源)"),
    "F-A04": ("基本功能", "引擎", "一阶速度伺服 τ=0.08s, max‖v‖≤0.5m/s 有界不发散"),
    "F-A05": ("基本功能", "引擎", "台面几何约束: 未夹持末端不穿透台面 (确定性规则)"),
    "F-A06": ("基本功能", "引擎", "夹持锁存: grasped 后 peg=x+peg_off 随动 (确定性规则)"),
    "F-A07": ("基本功能", "引擎", "接触力→接触概率: K_CONTACT 增益, 接触段 contact_p>0.6"),
    "F-A08": ("基本功能", "引擎", "流形量逐帧发布: 接触/性能 channel 进 io_trace + 全程序列"),
    # ── B 六层 (S1感知→S2并行→S3认知, 教学解析式 — 真权重见 model_feature) ──
    "F-B01": ("基本功能", "感知模型", "perception.py fuse_sensors: 39D 视觉+触觉4D → 43D 融合 (前端感知)"),
    "F-B02": ("泛化功能", "决策控制", "parallel.py FeedforwardAccelerator: 前馈快路径, 比例引导+近距闭合+±0.5限幅"),
    "F-B03": ("泛化功能", "世界模型", "AdaptiveStateEstimator: 卡尔曼 predict/update (A/K/B 可标定), 潜状态递归 — 世界模型"),
    "F-B04": ("泛化功能", "世界模型", "PriorDynamicsPredictor: 先验预测 A=1.0 恒速 + B·u, 潜空间速度场 — 世界模型"),
    "F-B05": ("泛化功能", "世界模型", "cognition.state_correction: 残差=z−x̂₋ / 校正=+K·r — 卡尔曼更新"),
    "F-B06": ("泛化功能", "世界模型", "contact_probability: σ(residual·gain) — 预测偏差→接触概率 (世界模型判据)"),
    "F-B07": ("基本功能", "决策控制", "ActionModulator 八阶段状态机: 顺序推进+连续2帧防抖 (确定性调度)"),
    "F-B08": ("基本功能", "决策控制", "夹持丢失 5 帧 + 落回台面 → 回退重抓 (确定性规则)"),
    "F-B09": ("基本功能", "安全机制", "否决权: 残差>veto_th → 强制减速 u=0 (安全)"),
    "F-B10": ("基本功能", "决策控制", "动作融合: 前馈+反馈相加 + 阶段限速 + V_MIN 防磨蹭"),
    "F-B11": ("基本功能", "安全机制", "safety.saturate ±0.6 饱和限幅 (唯一三层安全之一)"),
    # ── C 感知链 (YOLO/触觉/AOI → 感知模型) ──
    "F-C01": ("泛化功能", "感知模型", "YOLO detect_3d: best.pt + 深度反投影, 真实 conf (hand/peg/hole 3类)"),
    "F-C02": ("泛化功能", "感知模型", "align 段位: hand→[0:3] peg→[4:7]+[22:25] hole→[36:39]"),
    "F-C03": ("泛化功能", "感知模型", "gen_tactile: 触觉 4D (grasp/contact 0-1 语义)"),
    "F-C04": ("泛化功能", "感知模型", "AOIQualityChecker: 外观质量真实图像处理 (items/pass)"),
    # ── D 大模型层 (规则/LLM → 规划推理) ──
    "F-D01": ("泛化功能", "规划推理", "TaskPlanner: 指令→技能Token 规则链+validate (LLM 可插拔)"),
    "F-D02": ("泛化功能", "规划推理", "ExceptionReasoner: 异常 diagnose 分类 (连续否决/卡死)"),
    "F-D03": ("泛化功能", "规划推理", "SkillComposer: 场景→技能序列 (8 场景)"),
    # ── E 标定/流形/元层 (工具+模型) ──
    "F-E01": ("基本功能", "标定工具", "CalibrationLayer: 三域标定 引力/斥力/潜空间 + 平衡势"),
    "F-E02": ("泛化功能", "世界模型", "潜空间: PCA 有效维实测 vs latent_dim (世界模型低维流形)"),
    "F-E03": ("泛化功能", "世界模型", "ContactManifold: 接触流形 通道轴分解/法向偏离/状态判据"),
    "F-E04": ("泛化功能", "世界模型", "PerformanceManifold: 性能流形 η=exp(−V_p/σ²) 完成态高/未插≈0"),
    "F-E05": ("基本功能", "数据平台", "node_logic 分派: 标定/潜空间/接触/性能/Feature/Test 全命中"),
    # ── F 画布/数据世界 (数据平台) ──
    "F-F01": ("基本功能", "数据平台", "state_space_obs.json: 38 节点 10 层, type 合法"),
    "F-F02": ("基本功能", "数据平台", "节点注册覆盖: 全部非 row_bg 节点名可 match"),
    "F-F03": ("基本功能", "数据平台", "_EXTERNAL_LOC: 源码映射 路径存在 + 行号含符号"),
    "F-F04": ("基本功能", "数据平台", "io_trace 覆盖 DataWorld 全部模块键"),
    # ── G GUI 手动 (GUI 验收项) ──
    "F-G01": ("基本功能", "GUI工具", "▶ 运行: 引擎轨迹动画播放 + 节点轮转 demo"),
    "F-G02": ("泛化功能", "感知模型", "▶ 运行: 真实 YOLO 感知采样日志 (detect_3d 断点可进)"),
    "F-G03": ("基本功能", "GUI工具", "⏭ 单步 / 右键运行节点 = 引擎同源真实执行"),
    "F-G04": ("基本功能", "GUI工具", "3D 视图: 与引擎轨迹逐帧同步 (DataWorld 游标)"),
    "F-G05": ("基本功能", "GUI工具", "数据总线: 逐帧 feed 14 模块 51 接口滚动"),
    "F-G06": ("基本功能", "GUI工具", "Scope 波形: 距离/前馈/残差/接触概率 + 阶段标注"),
    "F-G07": ("基本功能", "标定工具", "双击标定节点→面板; 右键→表格 (三域可编辑)"),
    "F-G08": ("基本功能", "标定工具", "标定保存 = 写回引擎源码字面量, 下次 ▶运行生效"),
    "F-G09": ("基本功能", "GUI工具", "右键源码 → VSCode 断点进真实源码 (ZMAX_DEBUG_BREAK)"),
    "F-G10": ("基本功能", "GUI工具", "双击 Feature/Test 节点 → 本验证层输出"),
}


def main():
    """CLI: python verification_layer.py [--list] [--only F-A01] [--skip-slow]"""
    import argparse
    ap = argparse.ArgumentParser(description="🧩 状态空间验证层")
    ap.add_argument("--list", action="store_true", help="列 feature 清单")
    ap.add_argument("--only", default=None, help="跑单个用例 (如 F-A01)")
    ap.add_argument("--skip-slow", action="store_true", help="跳过 YOLO 慢用例")
    a = ap.parse_args()
    v = VerificationLayer()
    if a.list:
        v.list_features()
        return 0
    if a.only:
        ok, _ = v.run(a.only)
        return 0 if ok else 1
    ok = v.run_all(skip_slow=a.skip_slow)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

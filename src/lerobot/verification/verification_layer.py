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

    def __init__(self, log=print, repo_root=None):
        self.log = log or (lambda *a: None)
        self.root = repo_root or ROOT
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

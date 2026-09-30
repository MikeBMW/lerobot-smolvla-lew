# 断点"还是不进"的收尾 + L2 兼容勾选框 + 装配耗时 (2026-09-16 下半场, v5.6.11/v5.6.12)

> 上半场 (L2 兼容接线 / vision 只给 L3 档 / spec 加载断点不绑定 / 同口径 A/B / 画布补线) 见
> `references/l4-l2-tier-wiring-and-breakpoint-binding-2026-09-16.md`。本篇只记它之后的**新**内容。

## 一、老倪第三次「还是进不了断点」→ 让执行证据与调试器解耦

**先取证再动手**（这次差点误判成"老倪没重启"）:
```bash
ps -eo pid,lstart,args | grep '[s]tudio.py'            # GUI 启动时间
ls -l --time-style=+%H:%M:%S tools/gui/simulink_module.py tools/gui/state_space_sim_real.py
```
实测: GUI 09:13 启动、代码 09:05/09:09 改 ⇒ **不是旧进程跑旧代码**。
**规程: 报"断点还是不进"时按 ①进程启动时间 vs 文件 mtime ②档位是引擎路径还是 L4Demo
③断点是否在首行可执行语句 ④模块加载方式(绑定) 逐条量, 别先猜用户操作。**

两条**不依赖调试器**的证据（`parallel.py::forward` 真身开头, v5.6.12 落地）:
```python
if os.environ.get("SS_FF_BREAK") == "1":        # 硬停开关, 照 ZMAX_DEBUG_BREAK 惯例; 绑定失败也能停
    try:
        import debugpy as _dbg
        if _dbg.is_client_connected(): _dbg.breakpoint()
    except Exception: pass
self.n_calls = int(getattr(self, "n_calls", 0)) + 1
if self.n_calls % 100 == 1:
    print(f"🧠 前馈加速器: MLP 真身执行 #{self.n_calls} (域内 {self.n_mlp} · 守卫 {self.n_guard})", flush=True)
```
并把计数挂进老倪正在看的那行引擎进度日志（每 25 步那条）:
`[25/4000] 阶段=… · YOLO 检出率 … · 前馈 MLP真身 26/守卫 0`; 未启用时补
`(未启用: SS_USE_MLP≠1 → forward 被解析覆盖)`。
**一句话判两半**: 日志 N>0 而断点不停 ⇒ 绑定/断点位置问题; N==0 ⇒ 档位/勾选问题。
两臂实测: `SS_USE_MLP=1 → n_mlp=30/30 · 守卫 0 · n_calls=30` ‖ `不设 → 0/0 · n_calls=-1`
（`n_calls=-1` = 函数一次没进, 就是"从没执行"的铁证）。

## 二、「为什么运行了很长时间才进断点」= 装配链耗时（实测数字）

```
vision=True : import 0.98s → 构造(含 YOLO 对齐器) 2.13s → ★第一次进 forward 3.52s
vision=False: import 0.92s → 构造                1.96s → ★第一次进 forward 1.96s
```
引擎侧只要 2~3.5s。老倪体感的"几分钟"在更前面: `ensure_scene()` 生成场景 XML → worker 起 →
L4 档默认勾 INTACT ⇒ 起 **INTACT 子进程（独立 venv/py3.10）+ 加载权重 + 首次真推理**（CPU ~0.11s/步）
→ 勾「🧩 L2 兼容」还要**加载 YOLO 对齐器**（历史实测首次 10~40s，主线程）→ 之后才 `run()` 第一步。
再叠加架构口径: **▶运行 = 引擎先同步跑完整轮（L4 档 4000 步），跑完才在画布逐节点回放** ⇒
断点停在"引擎阶段"，画布动画在其后（体感更长）。
提速选项: 取消「🤖 L4 用 INTACT 节点执行」（走解析链，不起子进程/权重）或取消「🧩 L2 兼容」（省 YOLO）。
可选补救: 装配分阶段计时日志 —— 画布就绪 / 场景 OK / 权重加载完 / 首次推理 / 引擎开跑 各打时间戳。

## 三、勾选框入口 (v5.6.11, 老倪: "L4 档加一个勾选框「🧩 L2 兼容（前馈 MLP + YOLO）」")

`chk_l2_compat = QCheckBox("🧩 L2 兼容 (前馈 MLP + YOLO)")` 默认勾选, FlowBar 与
「🤖 L4 用 INTACT 节点执行」「🎯 L4 意图 → DiT 精炼」同排; **必须 `tl.addWidget(...)`**（老倪踩过
"创建了但忘挂布局 → 界面完全不可见且无报错"; 加控件 = 创建 + 连接 + addWidget 三件套）;
tooltip 写**实测代价**（0.42→6.82mm · 2.1×）与等效环境变量 `SS_L4_L2_COMPAT=0`;
装配块主线程读控件 → `self._l2_compat_on` → 判定 `_l4_cap ∧ ¬demo_cap ∧ _l2_compat_on ∧ env≠0`,
日志打「L2 兼容勾选框 = ✅/⬜」。
验收: `tools/verify_l2_compat_checkbox.py`（offscreen **11/11**）: 存在/文字/挂布局(FlowBar)/同排/
默认勾选/tooltip 含实测数字/点击可切换/装配块读控件/状态参与判定/仍受环境变量约束。
**默认值取舍**: 按"未证明提升不进默认档"本应默认关; 老倪明确要求 L2 在 L4 跑 ⇒ 最终 = 勾选框
**默认勾选 + tooltip 明写代价**（把取舍摆到用户面前, 而不是替他默认）。v5.6.11 commit 8cb86102。

## 四、画布 JSON 补线: 先验证再落盘（本轮写坏过一次）

插入 desc 时多打一个引号 → `flows/state_space_obs.json` 当场写坏（JSONDecodeError char 33255）。
正确顺序: `cp flows/state_space_obs.json /tmp/flow_backup_$(date +%H%M).json` → 构造新文本 →
**`json.loads(src2)` 断言通过** → 才 `open(p,"w")`; 写后逐字段比对旧连线
（`json.dumps(x, sort_keys=True)` 逐条）证明 0 变化; 已写坏就从备份恢复再重跑（本次即如此）。

## 五、其它实测小项

- `ultralytics` 只在 **gui-venv311**（8.4.126）; `~/lerobot-venv` 没有 ⇒ 任何 `vision=True` 的引擎跑法
  在那儿必 `ModuleNotFoundError`; 跑 vision 相关 A/B 一律用 gui-venv311。
- 本机 git push 偶发 `GnuTLS recv error (-110)`（`curl -sI https://github.com` 仍 200）⇒
  `git -c http.version=HTTP/1.1 -c http.postBuffer=524288000 push origin main --tags` 重推即成功。
- 版本纪律照旧: 五处同步（studio.py 3 处 + changelog 摘要 + update_checker + version_sync +
  docs_sync 两键）+ VERSION.md 行 + tag push; 本次连推 v5.6.9→v5.6.12。

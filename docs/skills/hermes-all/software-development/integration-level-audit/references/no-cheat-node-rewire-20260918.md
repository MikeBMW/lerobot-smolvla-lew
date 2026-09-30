# 假接入形态 0: "转发上游" (2026-09-18 实例 · 2D→3D 解算节点)

## 现象

画布节点名写「📐 2D→3D 解算」, 逻辑却是:

```python
det3d = _YOLO_CACHE.get("det3d")          # 上游 🎯 YOLO 3D 节点算好的
aligned = aligner.align(obs39, det3d)     # 只是把它拷进 39D 段位
```

→ 这不是 2D→3D, 是**搬运上游输出**。上游 `detect_3d` 在仿真里用的内参(cam_fovy)/外参
(cam_pos/cam_mat0)/深度(depth head) **全是仿真白送的**; 真机没有这三样 → 该节点在真机上
永远出不来 3D, 而仿真里一切正常。

**实测对照 (同一份代码, 同一帧口径)**:

| 源 | 3D 点 | 2D 框 | depth / K / ext | gaps |
|---|---|---|---|---|
| 仿真 (metaworld) | 3 | — | YOLO depth head / camera_info / T_base_cam | 0 |
| 真机帧 (D405 归档) | **0** | **2** (conf 0.929 / 0.922) | None / None / None | 2 (无深度·无内参) |

⇒ "真机看不到 3D 框" **不是模型问题**(框检得出来), 是**标定缺失 + 节点只做转发**。

## 审计判据 (加到形态清单里)

打开节点逻辑, 问一句: **它的输入是"感知给的原始结果"(原始帧 / 检测框), 还是"别人的输出"?**
输入是别人的输出 → 该节点的名字所声称的能力**根本没有实现**, 只是链路里的一段搬运工。
配套看: 该节点自称的参数 (本例 `intrinsics: camera_K, method: depth|hand-eye`) 有没有真被用。

## 改造套路 (老倪要求「仿真也不许作弊, 要用感知给过来的结果」)

1. **分清合法/非法输入**:
   - 合法 = 机器人**自身**状态 (关节/末端位姿): 真机是编码器, 仿真是 FK —— 它就是传感器。
   - 非法 = 被操作对象的真值 (env obs 段 / 仿真几何 / 白送的内参外参深度)。
2. **只吃** ①感知原始输出(检测框) ②机器人自身位姿 → **自己解算**(自监督求解器/标定)。
   本例: `Box3DSolver` (唯一先验 = 工件被夹持 ⇒ 中心 = TCP + R(q)·off; 未知 P + off 一起解)。
   惰性单例 + 状态文件 `models/box3d_state.json` 持久化, 攒够数据自动拟合。
3. **缓存里留不作弊凭证**: 输出旁挂 `used_env_module_truth: False` / `used_sim_geometry: False`;
   仿真真值**只允许事后打分写日志**, 不进任何输出。
4. **未标定时不产出假值**: 明确打"攒数据中 n 帧 · 位姿多样性还差 X — 本帧不产出假 3D", 返回 False。
   不要用上次估值或上游结果填空。
5. **headless 自检 (不启动 GUI)**:
   `sys.path.insert(0,'tools/gui'); import node_logic as N; N.match_node('📐 2D→3D 解算')` → 应返回
   新 key; 再 `N._box3d_ensure()` 看解算器模式 (已知工具零点 / 偏移未知)。
   画布节点改码后**必须重启**控制台才生效 (`systemctl --user restart zmax-studio`)。

## 两个配套坑 (都会让改造"看着生效其实没生效")

### ① 顶层常量惰性求值 — 插在常量定义之前会崩 import

`node_logic.py` 的 `_REPO_ROOT` 定义在文件**后半段**(~2397 行)。在它之前插入的**模块级**代码
引用它 → `NameError` → **import 崩, 控制台直接起不来**。正解:

```python
def _box3d_repo_root():
    try:
        return _REPO_ROOT              # 文件后半段定义的那个
    except NameError:
        return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

_BOX3D = {"solver": None, "path": None}       # path 惰性填, 别在模块级拼路径
def _box3d_state_path():
    if _BOX3D["path"] is None:
        _BOX3D["path"] = os.path.join(_box3d_repo_root(), "models", "box3d_state.json")
    return _BOX3D["path"]
```

通用规则: 往大文件里插模块级代码前, 先确认它引用的每个常量**在插入点之前**已定义。

### ② "缺标定"被误报成"0 检出" — 它把已经检出的框一起丢了

`estimate_3d` 在"无内参"分支:

```python
else:
    meta["gaps"].append("无内参 (K 与 fovy 都缺) → 无法反投影")
    return det3d, meta          # ← det3d 还是空的, 但 res 已经把框检出来了
```

此时 `res = self.model.predict(...)` 已经跑完、框就在手里, 却随 return 一起被丢掉 → 下游打印
"检出=0" → 看起来像"模型在真机上看不见"。**这类误报会让排查方向整个跑偏** (去查域差/换权重,
而真因是标定)。修法: 该分支仍回传 2D 框 + 明确 note, 并**只作 2D 用、绝不塞进 3D 槽**:

```python
meta["boxes_2d"] = [{"cls": res.names[int(b.cls)], "conf": round(float(b.conf), 4),
                     "box_px": [round(float(v), 1) for v in b.xyxy[0]]} for b in res.boxes]
meta["n_boxes_2d"] = len(meta["boxes_2d"])
meta["notes"].append("2D 框已给出, 3D 不可用 (缺标定); 补 K/外参/深度后才出 3D")
```

判据 (改造后的期望输出): `3D点=0 · 2D框=2 [{'cls':'光模块','conf':0.929,...}] | depth=None K=None
ext=None gaps=2`, 并跟一句"要出 3D 框: ① 机器人动作自标定 … ② 米制深度或 plane_z 回退"。

## 相关

- 视觉侧的算法与全部实测数字 (含"框四条边才可辨识"、工具零点示教把相对距离压成 0、
  只用 P + 已知平面做像素→3D): `robot-vision-3d-localization/references/mono-box-3d-selfcalib-20260918.md`
- 假接入其它形态与四级阶梯: 本技能 SKILL.md。

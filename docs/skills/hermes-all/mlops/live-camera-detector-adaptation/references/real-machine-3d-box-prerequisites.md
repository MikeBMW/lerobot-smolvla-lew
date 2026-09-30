# 真机为什么没有 3D 框 (而仿真有) —— 诊断清单

配套 SKILL.md §7.2。场景: 用户问「仿真里 YOLO 能出光模块 3D 框/边界框, 真机应该一样, 怎么没看到?」
**先答根因再答方案**, 而且先分清是"模型没看见"还是"管线把框扔了"。

## 一、先量: 同一条链路两侧的实测对照 (2026-09-18)

同一份代码 (`YoloStateAligner.estimate_3d`), 只换源:

| 源 | 3D 点 | 2D 框 | depth | K | ext | gaps |
|---|---|---|---|---|---|---|
| `--source sim` | **3** {hand, hole, 光模块} | — | YOLO depth head(仿真校准) | camera_info/标定 K | T_base_cam | 0 |
| `--source file:<真机帧目录>` | **0** | **2** (光模块 conf 0.929 / 0.921) | None | None | None | 2 |

结论: **模型在真机帧上看得见** (conf 0.93), 3D 一个点都没有 —— 少的是标定, 不是模型。

## 二、根因 (代码级, 已修)

`src/lerobot/policies/yolo_3d/yolo_state_aligner.py` 的 `estimate_3d`:

```python
res = self.model.predict(img_bgr, conf=conf, verbose=False)[0]   # ← 框已经拿到
...
else:   # 无内参 (K 与 fovy 都缺)
    meta["gaps"].append("无内参 → 无法反投影")
    return det3d, meta        # ← 直接 return, 已检出的 2D 框随 return 一起被丢掉
```

后果: 下游只看到 `det3d={}` → CLI 打「检出=0」→ 看起来像"模型在真机上什么都看不见",
其实是"没标定把框扔了"。修法 (2026-09-18): 该分支改为**如实回传 2D 框**再 return —

```python
meta["boxes_2d"] = [{"cls": res.names[int(b.cls)], "conf": round(float(b.conf), 4),
                     "box_px": [round(float(v), 1) for v in b.xyxy[0]]} for b in res.boxes]
meta["n_boxes_2d"] = len(meta["boxes_2d"])
meta["notes"].append("2D 框已给出, 3D 不可用 (缺标定); 补 K/外参/深度后才出 3D")
```

`tools/real_yolo_perceive.py` 同步改打印 + 结论, 不再把两种情况混为一谈:

```
[real] #0 0.34s 3D点=0 · 2D框=2 [{'cls': '光模块', 'conf': 0.9287, 'box_px': [...]}] | K=None ext=None gaps=2
[real] ⚠️ 0 个 3D 点, 但 **2D 检出 2 个框** —— 缺标定导致无法反投影, 不是模型没看见。
```

**铁律**: 见到「0 检出 / 无框」先问一句 **"是模型没看见, 还是管线把框丢了?"** ——
查 `meta.n_boxes_2d` / `aligner._last_res` (GUI 的 2D 框正是读 `_last_res`, 所以真机 2D 框能显示、
3D 视图空 —— 用户看到的就是这个现象)。

## 三、3D 缺的三样, 仿真是白送的, 真机一个都没有

| 输入 | 仿真 | 真机现状 | 为什么 |
|---|---|---|---|
| 内参 K | `cam_fovy` 白送 | **无** | UVC 直读只给像素; D405 的 `realsense2_camera` 驱动没装在 Orin → `/realsense/*` Publisher=0 → 拿不到 `camera_info` (图里有订阅者 ≠ 有帧) |
| 外参 T_base_cam | `cam_pos/cam_mat0` | **无** | 手眼标定从来没做过 |
| 米制深度 | MuJoCo 真值 或 仿真标定的 depth head | **无** | 同上没驱动 → 无 aligned depth; YOLO depth head 是按仿真渲染标定的, **禁止**在真机帧上用 (用了就是假证据) |

## 四、怎么把真机 3D 框做出来 (按性价比排序, 路一不需要任何深度传感器)

1. **机器人拿着的工件 —— 用运动学, 不用相机深度**: 中心 = `TCP + R(四元数)·实测偏移`,
   姿态 = TCP 四元数, 尺寸 = 卡尺实测 → 这就是 base_link 里的真实 3D 框 (与相机无关)。
   要画到图像上/和 2D 对齐, 只需投影 P —— **而 P 正是机器人动作自标定给的** (`models/real_cam_proj.json`),
   且 P = K·[R|t] 已把内参 + 手眼外参收进一个矩阵 ⇒ 一趟探针同时补上"3D 框缺的投影"和"标注的标定",
   不重复劳动。现场只多两件事: 量尺寸 + 量工件相对 TCP 的偏移。
2. **机器人没拿的物体 (孔位/料盘)**: 这才真需要相机深度 —— 二选一:
   ① Orin 装 RealSense ROS 驱动 → 米制/aligned depth → 通用 3D;
   ② 不装驱动就用 `plane_z` 光线-平面回退 (台面高度量一次), 对台面上的目标成立。
3. **通用"像素→米"反投影**: 还要单独标 K —— 探针几何是浅景深, 从 P 反解内参**不可辨识**
   (实测反投影 1.2px 的拟合里 fx 只有 175, 真值 610)。2D 出框够用, 3D 反投影不行。

## 五、诊断顺序 (照抄)

1. 跑 `tools/real_yolo_perceive.py --source file:<真机帧目录> --weights models/yolo_peg_live.pt --conf 0.25`,
   看 `3D点` 与 `2D框` 两个数 —— 先定位是检测问题还是标定问题。
2. 在役权重没框 → 走域适应 (见 SKILL.md §0/§1); 有框但 3D=0 → 继续。
3. 看 `depth / K / ext / gaps` 四个字段: 缺哪个补哪个, 别一起上。
4. 工件类目标 → 走路一 (运动学 + 探针 P); 环境类目标 → 路二 (深度/plane_z)。
5. **不要用仿真域的 K/fovy/深度"顶上"** —— 那是假证据, 用户会目检画面细节并追问实际执行。

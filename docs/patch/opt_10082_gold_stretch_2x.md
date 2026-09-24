# 补丁: 10082 金手指拉长口径 → **短边 ×2** (交工控机侧) — 2026-09-24

## 问题
老倪: 「金手指拉长的太长了，拉长三倍即可，找到金手指，拉长三倍」→ 随即改口径「都改成拉长2倍」。

现有实现 (`cam_finger_10082_work_v3.py::warp_goldfinger_topview`):

```python
top_img = warp_goldfinger_topview(pDstData, imgWidth, imgHeight)   # ← 调用处没传 out 尺寸
...
def warp_goldfinger_topview(pDstData, img_w, img_h, out_w=None, out_h=None):
    if out_w is None: out_w = img_w      # = 2448
    if out_h is None: out_h = img_h      # = 2048
    src_points = [[400,1000],[2000,1000],[2000,1250],[400,1250]]    # 1600x250 的固定透视窗
    dst_points = [[0,0],[out_w,0],[out_w,out_h],[0,out_h]]
```
⇒ 一个 1600×250 的窗被映到 **2448×2048** = **横向 1.53× / 纵向 8.2× 拉伸** —— 这就是"拉得太长"的来源
(而且文件名一直写 `W1600_H220`, 名字与内容不符)。

## 补丁 (3 行, 用他们自己的函数, 不引入新依赖)

```python
# ① 先把固定透视窗按**窗内原比例**摆正 (1600x250), 不再拉成原图尺寸
top_img = warp_goldfinger_topview(pDstData, imgWidth, imgHeight, out_w=1600, out_h=250)

# ② 只把**短边拉 2 倍** (250 → 500), 长边 1600 保持不动  ← 老倪最终口径
top_img = cv2.resize(top_img, (1600, 500), interpolation=cv2.INTER_CUBIC)

# ③ 落盘文件名写真实尺寸 (名字别再撒谎)
topview_file_param = f"Finger_TopView_W1600_H500_{global_img_count:03d}.png"
cv2.imwrite(topview_file_param, top_img)
```

`/picture?kind=topview` 返回的就是这张 → 与「拉长 2 倍」对齐。

## 更好 (可选, 现场确认后做): 用 v4 模板法先**找到金手指**再拉长
老倪原话含"找到金手指" —— 意思是先定位条带再拉长。固定窗 `[400,1000]-[2000,1250]` 只在当前
摆放/产品下成立 (实测条中心 y 会漂 1008~1450, 条本身还带 +0.6~1.0° 倾角)。
若要做"找到金手指"：按 `zmax-aoi-service` 技能里的 **v4 模板法** (`gf_crop.py` / `gf_template.py`,
现场已交付过) 定位条带 → 取条带 ROI → 短边 ×2 → 输出。这样换产品/换工位也不用改窗口。

## 4060 侧现状 (已上线, 不依赖本补丁)
判据图**已改从 `?kind=origin` 原始图自裁** + **短边 ×2**（长边不动）：
- 自动: `tools/aoi_exposure_fix.py::clean_judge_frame(k=2)` —— 切过曝带/死白列后只留金手指条再 ×2
- 手动: 质量检测终端「🎯 框选拉伸」在原始图上拖框 → 该矩形短边 ×2（倍数由「拉长」框控制, 默认 2）
- 实测: 条带 1623×135 → **1623×270**（×2）; k=1/2/3 分别 135/270/405 逐级可验
⇒ 即使 10082 的 `?kind=topview` 仍是 8.2× 或空图，窗口判据图也已经是「×2」口径。

## 验收
```bash
# 工控机本机
curl -X POST http://127.0.0.1:10082/capture_detect && sleep 1
curl -s "http://127.0.0.1:10082/picture?kind=topview&meta=1"     # 看 size/文件名 (应含 W1600_H500)
# 4060
cd ~/lerobot-smolvla-lew && ./gui-venv311/bin/python tools/aoi_exposure_fix.py <origin.png> 2
#   期望打印: 短边高 XXX→2XXX (×2.0) · 长边不动
```

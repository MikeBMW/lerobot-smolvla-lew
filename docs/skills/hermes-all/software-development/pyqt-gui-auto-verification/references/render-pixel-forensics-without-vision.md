# 无视觉时"看懂"一帧画面 + 判定用户屏幕上是哪个状态 (2026-09-17 实战)

> 场景: 用户拿"你看这画面里 XX 不对"质疑结果, 而**本模型看不了图**。
> 不要靠"再截一张图""让用户描述" —— 用下面三件套把"屏幕上是什么"变成可断言的数字。
> 项目侧落地工具 (Z-MAX 仓库) 与领域语义见 `zmax-console` 技能的
> `references/metaworld-insert-semantics-and-pixel-forensics-2026-09-17.md`。

## 1) 抓窗口 → 与"已知状态候选帧"比对 (最有力的第一步)

```python
# 抓某个窗口: Qt 自带, 不依赖 ImageMagick/xwd
app = QApplication([]); pm = app.primaryScreen().grabWindow(wid)   # wid = wmctrl 第一列
pm.save("/tmp/win_now.png", "PNG")
```
候选帧 = 你能在**同一进程/同一机位**重放出来的那些状态 (初始态 / 跑完终态 / idle 回退帧)。
判定 `cv2.matchTemplate` **多尺度** (0.4~2.6 step 0.02) 找最佳相关与位置;
⚠️ 整体相关只作辅助 —— 静态背景占大头时 0.85 vs 0.96 差距不够判案。
**用"会动/有颜色的那个物体"的像素质心 + 包围盒当指纹**: 本次 (绿=光模块)
窗口窗格相关 0.9423、绿像素 323 vs 319、包围盒**逐像素一致**、质心差 0.2×0.6px ⇒ 结论确定。
另存一份对照 PNG 给用户目检 (`/tmp/cand_*.png`), 让他也能对齐"我在说的这一帧"。

## 2) 世界坐标 → 像素投影 + 自检 (有 3D 场景/相机时)

```python
cid = model.camera("corner2").id
cpos, cmat = data.cam_xpos[cid], data.cam_xmat[cid].reshape(3, 3)
f = 0.5 * H / np.tan(np.radians(model.cam_fovy[cid] / 2))
def proj(p):
    v = np.asarray(p, float) - cpos
    xc, yc, zc = cmat[:,0]@v, cmat[:,1]@v, cmat[:,2]@v
    depth = -zc                      # MuJoCo/GL: 视轴 = 相机 −z
    if depth < 0: depth, xc, yc = -depth, -xc, -yc   # 约定不确定时按符号兜底
    return (W/2 + f*xc/depth, H/2 - f*yc/depth) if depth > 1e-6 else None
```
**必须自检**: 投影一个"图里必然可见"的物体 (本次=绿色光模块中心), 其像素点要落在该颜色像素质心
附近 (实测差 3~4px)。**没自检过的投影不许拿来下结论** (符号/朝向错了会给出漂亮但反的答案)。

## 3) 纯文本"看图": 字符画 + 色类 + 几何标记叠加

- 降采样字符画: 每格取块均值 → 亮 `#` / 中灰 `·` / 暗空格; 目标颜色像素占比 >25% 打专用字母 (如绿=`P`)。
  96×48 够读场景结构 (注意物体在画面里可能只有几十像素, 只能定性)。
- 插入区放大: 逐像素分类 (绿/红/亮/偏蓝/暗) 打字符 → 能分清"哪块是盒体哪个面、杆从哪儿进"。
- **把投影点当标记叠到字符画上** (`M`=孔口 `G`=终点 `1/2`=物体两端 `W`=插槽立柱…) →
  直接读"物体 vs 目标特征"的相对关系, 这是"我看了一眼图"的等价物。
- 结论仍以数字为准 (mm/px), 字符画只用于**定位问题在画面的哪一块**。

## 坑 (本次踩到)

- **`grep`/`find` 找几何体时先确认几何挂在哪**: 该场景 `body("box")` **geoms=0**, 9 个 geom 全在
  **同名 unnamed 子 body** 上 → 按名字找 body 再扫它的 geom 会一无所获, 要全模型扫或遍历 children。
- **跨进程数字不可比**: 同一 seed 换个进程, 布局会漂 (本次实测盒体 y 差 0.2m)。
  所以"用户窗口"和"真值"必须在**同一进程**里量, 或先把真值落盘成文件再比。
- **带 `$(...)` 命令替换或超长拼接的 terminal 命令会被 Hermes 硬拦** (本次两次),
  文件读取/搜索一律用 read_file / search_files 工具, 别在 shell 里塞 `$(grep ...)`。

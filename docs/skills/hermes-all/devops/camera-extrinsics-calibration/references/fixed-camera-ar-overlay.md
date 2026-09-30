# 固定相机 AR 叠加: 配方与取证命令

配套 `camera-extrinsics-calibration` 的 SKILL.md。本文件是"动手时抄"的层面。

## 1. 解算器骨架 (7 参: f + rvec + t, 主点=图像中心)

```python
# 归一化提高 DLT 条件数
def _norm3d(P):  c=P.mean(0); d=np.linalg.norm(P-c,axis=1).mean()
                 s=np.sqrt(3)/max(d,1e-9); T=np.eye(4); T[:3,:3]*=s; T[:3,3]=-s*c
                 return T,(P-c)*s
def _norm2d(uv): c=uv.mean(0); d=np.linalg.norm(uv-c,axis=1).mean()
                 s=np.sqrt(2)/max(d,1e-9); T=np.array([[s,0,-s*c[0]],[0,s,-s*c[1]],[0,0,1]])
                 return T,np.column_stack([(uv-c)*s,np.ones(len(uv))])

A=[]                                    # 每对点两行
for (X,Y,Z),(u,v) in zip(Pn,un[:,:2]):
    A.append([X,Y,Z,1,0,0,0,0,-u*X,-u*Y,-u*Z,-u])
    A.append([0,0,0,0,X,Y,Z,1,-v*X,-v*Y,-v*Z,-v])
Pn_mat = np.linalg.svd(np.asarray(A,float))[2][-1].reshape(3,4)
P_mat  = np.linalg.inv(T2) @ Pn_mat @ T3

out = cv2.RQDecomp3x3(P_mat[:,:3])      # ⚠️ 可能返回 (retval,K,R) 三个值
K,R = (out[1],out[2]) if len(out)==3 else (out[0],out[1])
# 符号归一: K 对角取正、det(R)>0
f = float((K[0,0]+K[1,1])/2); t = np.linalg.inv(K) @ P_mat[:,3]

# 收细: 残差=重投影; 每个候选解都要求所有点相机系 z>0.02, 否则丢弃
from scipy.optimize import least_squares
r = least_squares(resid, p0, args=(P,uv), method='trf', x_scale='jac', max_nfev=8000)
```

多起点策略: 以 DLT 解为基准, 扰动 f(×0.6~1.6)、rvec(σ=0.25)、t(σ=0.15) 各几组;
**没有 DLT 解时**(点数 <6)才退化为粗猜(实测不可靠, 宁可不落盘)。

## 2. 自检 (写完必跑, 并把它变成接口字段)

```python
def selftest():
    # 物理合理的真值相机: 侧上方看台面
    C=np.array([0.30,-0.75,0.55]); tgt=np.array([0.70,0.20,0.18])
    zc=(tgt-C); zc/=np.linalg.norm(zc); xc=np.cross([0,0,1],zc); xc/=np.linalg.norm(xc); yc=np.cross(zc,xc)
    R=np.stack([xc,yc,zc]); t=-R@C
    uv,z = project(PTS, 520.0, R, t, 320., 240.)
    assert (z>0.05).all()                  # ← 这一句能拦住"点在背后"的假完美
    uv = uv + rng.normal(0,0.6,uv.shape)   # 模拟点选误差
    r = solve(PTS, uv)
    ok = abs(r['f']-520)/520 < 0.05 and r['rms_px'] < 1.5 and (np.array(r['z_m'])>0.05).all()
```
基准(修好 DLT 初值后的实测): f 误差 0.36% · RMS 0.46px · t 误差 2.6mm。
作为对照: 去掉 DLT 初值(只用多起点+LM) 实测 f=84.6 / z=1.4e4 m / RMS 2.4e8 px。
**不通过就不放行**(`SOLVERSELFTEST` 进响应体, 页面上直接能看到)。

## 3. 标定接口契约 (页面点选 → 解算 → 存盘)

- `GET /api/stable`: 采 1.2s TCP 报 `{drift_mm, stable, n}` —— 点选前的前置条件由服务端判。
- `GET /api/tcp`: 当前 TCP 真值 + `age_s`(帧龄必须能看见)。
- `POST /api/calib {"points":[{"uv":[u,v],"tcp":[x,y,z]},...]}`:
  - **<6 点直接拒**, 并告诉用户为什么(没有线性初值, 容易解飞)与"高低/左右都要变"。
  - 返回 `f / R_base_to_cam / t_base_to_cam / rms_px / err_px[] / spread_sigma_mm / range_mm / solver_selftest`。
  - 存 `data/scene/<cam>_calib.json`, 同时把点对也存进去(便于复算与复标)。
- `GET /api/verify`: TCP 投影 vs 运动掩膜, 回 `hits/total` + 逐样本 `inside/nearest_moving_px`。
- **接口自测**(不靠手点就能验管线): 用自检相机造 8 组对应点 POST 一遍, 断言解回的 f 接近真值、
  `solver_selftest=true`、能重投影回原像素(实测回投偏差 0.053px); **跑完立刻删掉那个假外参文件**并 `ls` 复核不存在。

## 4. "屏幕一直闪"的取证命令 (先量再改)

```python
# 拆 MJPEG 流的帧(按 boundary 切, 找 JPEG 的 FF D8), 逐帧比亮度/帧间差
# 稳的流: 亮度恒定(实测 124.1)、帧间差 ~1(只有噪声)
# 交付质量: 量帧间隔 -> 中位/max/std(实测中位 98ms 但 max 270ms = 交付抖动)
```
```bash
sudo dmesg -T | grep -iE "uvcvideo|USB disconnect|i915|drm|flip"   # 硬件/显示侧
nproc; uptime                                                        # 核数 vs load
ss -tn | grep -E ':(8791|8797)'                                      # 同一路流的消费者数
DISPLAY=:0 xrandr | head -6                                          # 显示模式/刷新率
```
四项全正常 ⇒ 问题在页面。此时查: 有没有重设 `img.src` · 有没有周期性重建 SVG/DOM ·
**有没有在图像 `load` 回调里重设 canvas 宽高**。

## 5. 浏览器里的页面验证 (经验证可行的四个断言)

1. **无 JS 抛错**: 顶层 `window.addEventListener('error', ...)` 把异常写到页面可见处, 不静默死。
2. **静发 load 事件不重画**: 记下画布上的标记像素 → 连发 30 次 `img.load` → 断言标记仍在、重画计数 0。
3. **JS/Python 投影同口径**: 把同一组 (f, R, t, 点) 两边各算一遍比最大差(实测 0.001px)。
   ⚠️ 注入假外参要写裸名 `CALIB={...}` 并把 `drawTube/proj` 等当成全局函数调用;
   `window.CALIB=...` 无效(脚本里是顶层 `let`)。
4. **渲染器不是死代码**: 喂真实录到的 3D 点跑一遍绘制, 断言"画出段数 >0 且上屏像素 >0",
   并报深度范围(实测 8 段 / 7570 像素 / 深度 0.69~0.78m)。

## 6. 轨迹状态机 (单一真源)

- 状态文件一个(如 `data/scene/traj_display.json`): `{show, baseline_n, plan_hidden, at}`;
  页面、发布器、服务都读它 ⇒ 不会出现"页面显示开、画面没画"这种不一致。
- **撤掉 ≠ 删数据**: 从规格里把这类元素挪到缓存文件(`_hidden_paths.json`), 再显示能原样恢复;
  录制侧(`/tmp/*.json` + jsonl)永远不动。
- 发布器每次循环先读开关: `show=false` 就直接清层(幂等), 避免"用户关了但发布器又画回来"。
- 按钮点了**立刻**跑一轮发布(不用等下一个周期), 否则用户会以为按钮没反应(周期 2s 也够慢)。

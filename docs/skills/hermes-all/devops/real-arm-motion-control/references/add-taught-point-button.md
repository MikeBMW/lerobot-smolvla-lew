# 新增「回点」按钮/回点技能 —— 命令级配方 (2026-10-01 实测)

场景: 老倪说「记录现在的位姿, 侧面点 N, 增加侧面点 N 的技能, 在表面检测窗口下面加按钮」。
全线 8 步, 全程**零运动**(录点只读、注册只改 JSON、验收走 arm=0 演练)。

## 1. 录点 (零运动, 人在现场)

```bash
# 先确认静止(连采 6 帧看极差/帧龄):
for i in 1 2 3 4 5 6; do python3 -c "import json,time;d=json.load(open('$HOME/zmax_data/rokae_sdk/tcp_out/latest.json'));\
print('pos=(%.6f,%.6f,%.6f) 帧龄%.1fs'%(d['x'],d['y'],d['z'],time.time()-d['ts']))"; sleep 0.4; done

python3 tools/record_point_sdk.py --record 侧面点2 --desc "表面检测观察位(侧面点2) · 现场实录"
# ⇒ 落 data/skills/l2_atomic/taught_points.json 的 points['侧面点2'] + 留痕 reports/aoi_points/侧面点2.json
python3 tools/record_point_sdk.py --show      # 只读看看当前位姿与稳定性
```

真值字段: `pos=[x,y,z]`(m) · `quat=[x,y,z,w]`(xyzw) · `frame=base_link` · `source=ROKAE SDK 直读 endInRef`。

## 2. 注册技能 (幂等)

```bash
cp tools/register_surface_pt1_skill.py tools/register_surface_pt2_skill.py   # 再改 id/name/point
python3 tools/register_surface_pt2_skill.py
```

技能体(回点类铁律四件套):
```json
{"id":"L2.goto_surface_pt2","name":"🎯 回到侧面点2","ros":"line_abs","quat":"taught",
 "point":"侧面点2","point_locked":true,"group":"AOI检测","guard":{"dz_down_limit_mm":20}}
```
- `quat="taught"` 关键: 不回姿态的话会沿用当前姿态 ⇒ 视角不对(点位的意义就是那个视角)。
- `point_locked`: 点位写死在定义里, 页面/接口只能送技能 id ⇒ 改不了点位。

## 3-4. 白名单 + 页面

```python
# tools/cam_live_stream.py
_CTL_ABS_SKILLS = { ... , "L2.goto_surface_pt2": "🎯 回到侧面点2" }
```
```html
<!-- tools/web/station.html: 与已有按钮同一行, 复用同一份实现 -->
<button id="b_spt2" onclick="gotoSurfacePt2(this)" ...>🎯 侧面点2</button>
<script>let _spt2={t0:0,timer:null};
async function gotoSurfacePt2(btn){return gotoTeachPoint(btn,_spt2,'L2.goto_surface_pt2','『🎯 侧面点2』','#spt2_msg','回到侧面点2');}</script>
```

## 5-6. 重启一次 + 语法自检

```bash
bash tools/start_station_stream.sh          # 白名单是模块常量 ⇒ 必须重启(页面热读不用重启)
python3 -c "import re;h=open('tools/web/station.html',encoding='utf-8').read();\
open('/tmp/s.js','w').write('\n'.join(m.group(1) for m in re.finditer(r'<script[^>]*>(.*?)</script>',h,re.S) if 'src=' not in m.group(0)[:60]))"
node --check /tmp/s.js && echo OK
```

## 7. 验收(arm=0, 零下发)

```bash
curl -s -X POST -H 'Content-Type: application/json' \
  -d '{"skill":"L2.goto_surface_pt2","speed":8,"arm":0}' http://127.0.0.1:8791/ctl/move
# 判据: 回执 msg=演练(未下发) · 日志里的目标 pos/quat 与录的点**逐位一致** · 环境校验 ✅ 包络内
curl -s 'http://127.0.0.1:8791/ctl/log?n=14'
```

## 坑 (实测踩过)

- 🔴 **别用 `arm=1` 当"应被拒"测试**: 只要有人在 8793 授权过(窗 10 分钟), arm=1 就是**合法下发**
  (2026-10-01 实测回 `已下发(真动)`; 当次 Δ=(0,0,0)mm 才没动)。授权只从工位总览来, 代发前先看页面授权状态。
- `data/` 是**软链** ⇒ `git add data/skills/...` 报 `fatal: pathspec ... beyond a symbolic link`;
  技能库/示教点属数据盘资产, 快照 `~/zmax_data/l2_points_snapshots/`。
- 白名单不热读: 忘了重启 ⇒ 页面按钮点了回 `whitelisted: false` / 不下发。
- 录点前一定看**帧龄**(>2s = 陈旧) 与**位置范数**(≈0 = 会话陈旧的全 0 坏值) —— 工具会拦, 但现场先看一眼更快。
- 两个点若只差姿态(位置几乎相同), 位置 Δ 会是 0 ⇒ 验收只能靠 quat 逐位比, 别只看 Δ。

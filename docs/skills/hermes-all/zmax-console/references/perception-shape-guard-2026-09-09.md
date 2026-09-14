# 感知估值形状守卫 — F5 下 np.concatenate "0D vs 1D" 崩 (2026-09-09)

## 症状
真实化运行启动即失败:
`ValueError: all the input arrays must have same number of dimensions, but the array at index 0 has 1 dimension(s) and the array at index 3 has 0 dimension(s)`
栈在 `state_space_sim_real.py` 39D 视觉拼接 `np.concatenate([self.x, [gripper], self.v, self._peg_cur, ...])` (index 3 = `_peg_cur`)。
**命令行连续两次复现不了, 只发生在 GUI + F5 attach 场景** (调试态下 detect_3d 偶发输出异常形状检测值)。

## 排查法
`_peg_cur` 0D 唯一来源 = `np.asarray(self._vis["peg"], dtype=float)`。
先 `grep -n "_peg_cur\s*=" state_space_sim_real.py` 列出全部赋值点 (仅 4 处: reset=None / 夹持 x+off0 / 视觉 asarray / R0 o[4:7]) 缩小范围, 别猜。
CLI 复现不了 ≠ 没 bug: 换个运行场景 (GUI 进程 + attach / 先跑过快演 sim 再跑真实化) 常是触发条件。

## 修复 (双保险, 与幻影免疫同哲学 "宁可保旧不喂坏数据")
① **入口守卫** (检测值赋值处):
```python
if self._vis["peg"] is not None:
    _pv = np.asarray(self._vis["peg"], dtype=float).ravel()
    if _pv.size == 3:
        self._peg_cur = _pv
    elif getattr(self, "_peg_shape_warned", 0) < 3:   # 打点取证, 限次防刷屏
        self._peg_shape_warned = getattr(self, "_peg_shape_warned", 0) + 1
        self.log(f"⚠️ 防御: 视觉 peg 形状异常 {np.asarray(self._vis['peg']).shape} → 丢弃保旧估值")
```
② **concat 兜底** (拼接处局部变量, 不改 self._peg_cur 本体 → 控制语义 None=等待定位 不受影响):
```python
_pc = self._peg_cur
if _pc is None: _pc = np.zeros(3)
elif np.asarray(_pc).ndim != 1 or np.asarray(_pc).size != 3:
    # log 打点 (限 3 次) → 置零占位不崩
    _pc = np.zeros(3)
cur = np.concatenate([self.x, [self.gripper], self.v, _pc, ...])
```

## 教训
- 引擎每帧消费的感知估值 (视觉 peg/hole/hand 等) 赋值处都要形状守卫 — 0D/2D/None 三态都处理。
- 打点必须带来源 (检测输出 shape) 便于下次定位到 detect_3d。
- **改 `state_space_sim_real.py` 后必须重启 GUI**: worker 里 `from state_space_sim_real import RealStateSpaceSim` 走 sys.modules 缓存, 普通 import 不热重载 (与标定层 spec_from_file_location 每次运行重载不同)。GUI 表现为"改了没用"先查这个。

# 用户报"卡死了/鼠标能动其它不动" → 先 py-spy 查断点挂起 (2026-09-02)

老倪: "刚才怎么卡死了？就鼠标能动，其它的都不动了" — 两次都报整机卡死。

## 教训 (本次会话 5 轮弯路换来的铁律)
**GUI 进程活着但界面无响应 + VSCode 调试会话开着 → 第一动作就是
`sudo py-spy dump --pid <gui>` 看主线程栈, 别先做系统级诊断。**

错误排查顺序 (本次实测白花 5 轮, 全部正常):
1. uptime / free — 负载 1.0, 内存 6.7G/31G, 一切正常
2. journalctl -b -1 — 无 OOM / 无 kernel panic / 无 GPU Xid
3. dmesg / pstore — 无内核崩溃痕迹
4. WiFi / iwlwifi 日志 — 只有正常重连
5. sysstat sar — 内存提交峰值 88% 但没爆

最后 py-spy 一抓即中。

## 铁证 (py-spy dump 连抓 3 次, 全相同)
```
Thread 6232 (idle): "MainThread"
    _do_wait_suspend (pydevd.py:2268)      ← debugpy 断点暂停
    do_wait_suspend (pydevd.py:2199)
    fuse_sensors (perception.py:33)        ← 引擎内部源码断点
    _build_obs (state_space_sim.py:203)
    run ← _start_state_space_sim
```
= ▶运行 状态空间仿真 → 主线程同步跑引擎 sim.run() → 第 1 步就命中
perception.py 里的断点 → debugpy 把 GUI 唯一线程挂起等 VSCode 操作 →
界面全死 (鼠标是 X 服务器画的所以还能动) → 断点每步都命中 = 500 次暂停。

## 验证要点
1. **首次 dump 可能抓到残影栈** (本次第 1 次抓到 paint/simulink_module.py:2853,
   是挂起瞬间的渲染残留) — 必须连抓 3 次确认主线程都停在 do_wait_suspend。
2. do_wait_suspend 时线程状态是 **idle** 不是 active (等 VSCode 操作, 不占 CPU)。
3. 无 OOM/panic/Xid + 内核日志正常 = 不是真系统卡死。

## 恢复
- VSCode 里删掉引擎内部断点 (src/lerobot/policies/left_right/state_space/*.py
  或 yolo_3d) 或点继续 → GUI 立即活, **不用重启系统/GUI**。
- 想调引擎就接受每步都停 (500 步); 只想调节点逻辑就只留 node_logic 断点。

## 区分真系统卡死 (本次第 1 次报"卡死"是另一回事)
真卡死特征: uptime 显示刚重启 (LiveUSB 无持久 journal, 上次 boot 日志查
`journalctl -b -1`) + journalctl -b -1 末尾日志戛然而止 + 无 OOM/panic 记录。
本机 LiveUSB 无 swap + 31G 内存, 内存顶满会直接冻结 — 已建议加 8G swapfile 防御。

## 相关
- SKILL.md「VSCode 断点调试 node_logic 坑」根因 ④ 同机制 (引擎断点堵死播放)。
- 工具: gui-venv311/bin/py-spy (sudo env PATH=$PATH ... dump --pid N)。

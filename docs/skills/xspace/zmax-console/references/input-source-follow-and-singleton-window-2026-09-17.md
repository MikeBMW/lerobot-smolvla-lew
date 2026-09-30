# 窗口输入源不跟随画布「🔀 数据源切换」+ 单例窗口状态漂移 (2026-09-17 三次会话实测)

> 老倪: 「我调到仿真模式了, 应该输出 metaworld 的输出, 为什么在 YOLO目标检测 右键打开 输入图像,
> 还是显示现场的视频呢? 应该是仿真的视频啊」。两处根因都在代码里, 已修 + 取证, 不是推断。

## 一、根因 (两条, 缺一不成现象)

1. **入口参数写死**: `tools/gui/simulink_module.py` 右键菜单项 (a_input 分支)
   ```python
   from yolo_input_viewer import open_input_viewer
   open_input_viewer(self, module=self.module, source="real")   # ← 写死真机
   ```
   画布状态 (`📦 数据源节点 params.src_state`) 压根没读。
2. **单例窗口复用不比对状态**: `open_input_viewer` 里
   ```python
   win = getattr(YoloInputViewer, "_cur", None)
   if win is not None:
       if not win.isVisible(): win.show()
       win.raise_(); win.activateWindow(); return win      # ← 只抬窗口, 不管源
   ```
   ⇒ 上次开的是真机窗口, 这次画布在仿真也照样放现场视频。

## 二、画布状态源 (唯一权威, 别再另造)

| 项 | 位置 | 值 |
|---|---|---|
| 权威 | `📦 数据源节点 params["src_state"]` | `"仿真"` / `"真机"` |
| toggle | `SimulinkModule.on_toggle_src(node)` | 翻转 + `_save_param_to_flow` |
| 副本 | `module._data_source` | `"metaworld"` (仿真) / `"bypass_real"` (真机) |
| 画布自身默认 | `params.get("src_state", "仿真")` | 无该节点时 = 仿真 |

判空时跟画布自身默认 (仿真) 保持一致, 别默默退回真机。
流程文件 (`flows/*.json`) 里能直接核对当前态: `grep -o '"src_state"[^,}]*' flows/state_space_flow.json`。

## 三、修法三处 (缺一不可)

```python
# (a) 收敛的状态读取 (放在 SimCanvas 之前的模块级函数, 供菜单/窗口共用)
def _canvas_src_state(module):
    for n in getattr(module, "nodes", None) or []:
        st = (n.get("params") or {}).get("src_state")
        if st in ("仿真", "真机"):
            return st
    return "真机" if getattr(module, "_data_source", "") == "bypass_real" else "仿真"

# (b) 入口现读状态 + 菜单标签写明会开哪一路 (老倪一眼可见)
_cs = _canvas_src_state(self.module)
a_input = menu.addAction("打开输入图像 (%s)" % ("🧪 仿真 metaworld" if _cs == "仿真" else "🎥 真机 RealSense"))
...
open_input_viewer(self, module=self.module,
                  source="sim" if _canvas_src_state(self.module) == "仿真" else "real")

# (b') 单例复用窗口时对齐状态 (0=真机 / 1=仿真; setCurrentIndex 会触发 _switch 停旧源起新源)
_want = 0 if source == "real" else 1
if getattr(win, "cb", None) is not None and win.cb.currentIndex() != _want:
    win.cb.setCurrentIndex(_want)

# (c) 状态切换时推送 (on_toggle_src 末尾: 窗口开着就跟着切, 免用户忘记手动切)
_w = getattr(yolo_input_viewer.YoloInputViewer, "_cur", None)
if _w is not None and _w.isVisible():
    _want = 1 if p["src_state"] == "仿真" else 0
    if _w.cb.currentIndex() != _want:
        _w.cb.setCurrentIndex(_want)      # 数据根也会随 _switch→_set_annot_root 一起切
```

**通病化 (比本次修复更重要)**:
- 「**单例窗口 + 外部有状态开关**」组合必须做 (b') + (c): 只 `raise_()` 就是状态漂移
  (同族坑: 3D 视图复用窗口不换轨迹源、GL 窗口 close 后复用不重建 — 见 zmax-console 里
  「pyqtgraph GL 跨上下文 shader 失效」「3D 视图↔程序执行状态映射」两节)。
- 「**从菜单/双击打开的功能**」的参数必须**打开时现读状态**, 一律不许在调用点写死
  (同族: 画布档位 L2/L3/L4、数据源、图像尺寸/归一化口径)。写死 = 用户改了状态你却看不到, 老倪必然抓出。

## 四、取证 (`tools/verify_input_source_follow.py`, 全绿)

1. 画布状态取值 4 例: `src_state=仿真 → 仿真` / `=真机 → 真机` / 无节点 → 默认仿真 / 无节点但 `_data_source=bypass_real` → 真机。
2. 复用窗口源对齐 3 例 (真函数体 + 假窗口对象 `FakeWin/FakeCb`): 真机旧窗 + 画布仿真 → idx 0→1 且被 raise;
   仿真旧窗 + 画布真机 → idx 1→0; 两边一致 → 切换次数 0 (不乱切)。
3. **替代数据源真出帧** (证明"应该是仿真的视频"这句能兑现): 直接起真 `_SimGrabber(q, False)` 收 3 帧 —
   实测 `shape=(480,480,3)` · `src=sim:metaworld corner2` · `device=mujoco 渲染(非真机相机)`。
   ⚠️ 别只验证"窗口不报错": 替代源是否真出帧要单独测 (同族: 引擎"影子臂 calls>0 实为空转"的教训)。

桩写法要点: 用**真方法体** + 假屏幕/假窗口 (`staticmethod` 必须 `staticmethod(...)` 包一层, 否则被当实例方法绑定
self → TypeError 被 `except Exception: pass` 吞掉 → 假 PASS; 详见 pyqt5-gui-development
`references/multiscreen-window-clamp.md` 同名坑)。

## 五、重启纪律补充 (本次实测)

- 本会话控制台**确实在 systemd 下** (`zmax-studio.service`, MainPID 3003, `Restart=no`);
  `systemctl --user restart zmax-studio` **可用** (Hermes 会 flag 但自动批准), 重启后新 PID + 服务 active 自证。
- **重启前必须先问用户**: `studio.py` **没有自动保存**, 画布未落盘改动 (如刚 toggle 的 src_state) 会丢。
  判据: `ls -t flows/*.json` 的最近落盘时间 vs 用户刚做的操作 —— 本次 `flows/` 最近落盘 14:36,
  用户 16:00 的切换没落盘 ⇒ 重启前先说明"会丢未保存改动"并征得同意。
- 重启后**所有子窗口都不在了** (输入图像/3D/Scope), 汇报里要写清"请重新右键打开窗口"。

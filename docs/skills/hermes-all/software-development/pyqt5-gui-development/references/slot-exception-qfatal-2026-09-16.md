# 槽函数未捕获异常 = 进程消失 (qFatal) — VEH.3.04「发现硬件」崩因 (2026-09-16)

## 现象 / 用户原话
「控制台，发现硬件，怎么崩了」「VEH.3.04 发现硬件，又崩了」—— 窗口凭空消失，无弹窗、无报错。
`journalctl --user -u <gui-unit>` 里**只有正常启动日志 + 最后一行 "Consumed XXs CPU time"**, 没有 traceback
(qFatal 走 C 层 abort, 不留 Python 栈)。

## 真根因 (真 traceback, 靠 offscreen 手调 handler 逼出来)
```
studio.py:7372 in _on_discovery_result
    [(n, Z700_ROS2_NODES.get("real", {}).get(n, "")) for n in nodes]
AttributeError: 'list' object has no attribute 'get'
```
`Z700_ROS2_NODES["real"]` 定义是 **list**: `[("/tashan/robot_driver", "他山机器人驱动"), ...]` —— 对它调 `.get()` 必炸。
- 为什么"以前能用、今天才崩": 之前"发现硬件"必失败(发现线程里 ORIN_USER 还是废弃的 `nvidia` →
  Permission denied → 提前 return), **根本走不到这一行**; 修好账号/免密让发现真跑通后, 立刻踩中潜伏 bug。
  ⇒ 教训: "某个按钮以前点了没反应/不报错" 修通后, **紧接着的下一段代码要从没被跑过**, 必须重新验一遍。

## 逼出 traceback 的脚本模板 (qFatal 场景通用)
```python
import os, sys, time, traceback
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.getcwd())
from PyQt5.QtWidgets import QApplication
app = QApplication([])
import studio
w = studio.StudioMainWindow(); w.show()          # 必须 show(): 影响可见性/渲染路径
for _ in range(4): app.processEvents(); time.sleep(0.1)
hw = next(iter(w.findChildren(studio.HardwareModule)), None)
# 造/取真数据(这里直接跑真发现线程) → 然后**直接手调 handler**, 异常就抛给调用方
t = studio.HardwareDiscoveryThread(); res = {}
t.result_ready.connect(lambda r: res.update(r)); t.start()
while not res: app.processEvents(); time.sleep(0.05)
try:    hw._on_discovery_result(res); print("✅ _on_discovery_result 正常返回 (无异常)")
except Exception: traceback.print_exc()
```
要点: ①`w.show()` 不能省(可见性会改变控件/编号/渲染分支); ②类在 studio.py 里的用 `studio.XxxModule`
(别去别的模块 import, 会 ImportError); ③修完**同脚本再跑一遍**, 打印 "✅ 正常返回" 就是修复证据。

## 修复三件套 (已落地 commit 926cab8d)
1. 注册表 list/dict 双兼容:
   ```python
   _known = Z700_ROS2_NODES.get("real", [])
   _known_map = dict(_known) if isinstance(_known, dict) else {str(k): v for k, v in _known}
   ```
2. 树/表访问判 None: `_it = self.device_tree.topLevelItem(i)` → `if _it is not None: _it.setText(...)`
3. **渲染总闸** (根治这一类):
   ```python
   def _on_discovery_result(self, result: dict):      # 槽函数: 只做 try/except
       try: self._render_discovery_result(result)
       except Exception as e:
           self._log(f"❌ 发现结果渲染失败 (已拦截, GUI 未崩): {type(e).__name__}: {e}")
           traceback.print_exc()
   def _render_discovery_result(self, result: dict):  # 原实现整体搬进来
       ...
   ```

## 同批修的另一条链路 (相关但独立)
- 「无法连接 192.168.23.66」真因 = 发现线程里 `ORIN_USER = "nvidia"`(nvidia@.10 时代废弃账号),
  而当前 Orin 账号是 `tashan`。**硬件地址/账号类变更后, 要 grep 全仓库的旧值**, 别只改明显的一处。
- ros2 命令必须显式 `export ROS_DOMAIN_ID=0`(机器人在 domain 0, 用 23 查会误判"驱动没起")。
- GUI 的 ssh 路径全靠**免密**, 本机没密钥时一律连不上 → 生成 ed25519 并写入 `tashan@192.168.23.66`
  的 `~/.ssh/authorized_keys`; GUI 里的 `ControlPath=/tmp/orin-ssh.sock` 复用通道
  (`ControlPersist=120`) 空闲 2 分钟就消失, 别把它当故障。

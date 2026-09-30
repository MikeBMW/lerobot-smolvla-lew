---
name: hardware-free-e2e-verification
description: Use when 接硬件/厂商SDK的程序跑不了真机要出证据.
version: 1.0.0
author: hermes-agent
metadata:
  hermes:
    tags: [verification, hardware, vendor-sdk, e2e, stub, evidence]
    related_skills: [integration-level-audit, pyqt-gui-auto-verification, zmax-aoi-service, camera-frame-forensics]
---

# 无硬件端到端取证 (桩件跑真链路)

## When to Use
- 要交付/修改一个**接硬件的程序**(产线工控机 Flask 程序、厂商相机 SDK、机械臂服务、PLC 桥), 但本机没有那台硬件
  → 不能假装"跑过", 也不能只做语法检查就交
- 用户/现场反复会问「**实际怎么执行的? 你跑过吗?**」→ 必须给可复现的 PASS/FAIL 证据
- 改了接口语义/输出几何, 要证明"每档都对"而不是"我以为对"

## 核心手法(六步)

### 1. 桩件替掉厂商 SDK, 但**用 runpy 跑真文件**
别把逻辑抽出来单测就算完 —— 用 `runpy.run_path(<真文件>, run_name="__main__")` 跑程序**自己的启动路径**
(端口注册/参数解析/占用自检/线程启动都真跑), 只在 `sys.modules` 里预置桩模块:
```python
sys.modules["SciCam_class"] = <桩>; sys.modules["yolo_detector"] = <桩>  # 没装 flask 也可桩
runpy.run_path("/path/to/cam_xxx_work_v4.py", run_name="__main__")
```
桩只要覆盖被调用的名字(枚举/打开/抓帧/转换/存图), 图像用真图队列喂进去。

### 2. 真 HTTP 服务器 + 真请求
桩掉 flask 就没有端到端了。做法: `uv venv /tmp/x --python 3.12 && uv pip install --python /tmp/x/bin/python flask`,
再 `PYTHONPATH=<另一个venv>/lib/python3.12/site-packages` 复用已有的 cv2/numpy(**别重装几百 MB 的 opencv**)。
用 `urllib.request` 打每个端点, 覆盖: 正常 200 / 错误分支 / 未就绪 404 / 第二次启动撞端口。

### 3. 断言必须断到**内容级**, 不能只看 200
- 图片端点: `cv2.imdecode` 后断**宽高** (`(960,960)` / `(1455,70)` / `(2448,2048)`) —— 只断"字节数>0"会把
  "返回了 JSON 错误体"当成通过
- JSON 端点: 断关键字段(通道类型、判决、几何尺寸、角度); 落盘: 断文件名+尺寸在位
- 汇总成 `RESULT:PASS/FAIL`, 每条形如 `③ /picture 默认=原图(>3MB) / kind=crop=960x960`

### 4. 运动/伺服/闭环逻辑: 合成设备(plant)注入
真机不能动时, 把"下发"和"读回"做成可注入接口, 塞一个**带物理模型的假设备**:
```python
class FakePlant:  # 臂位移→图像里目标移动(带交叉耦合); 光轴方向 focus 呈二次曲线(峰在 3mm)
    def region(self): ...            # 返回与 x,y,z 相关的目标框 + 清晰度
    def send(self, skill, **kw): ... # 记录指令并按运动学更新自身状态
```
断言: 收敛(|误差|≤容差) · 限幅(单步/累计不超) · 否决(检测不可靠时**零指令**) · dry-run(未授权零指令) ·
退火爬坡到峰值。符号错(如 `Δarm = -M·e` 写成 `+M·e`)会**发散**, 所以必须有一条"收敛"断言专门抓符号。

### 5. 证据要可复现, 而不是一次性截图
每个测试留独立脚本 (`smoke_*.py` / `e2e_*.py` / `test_*_offline.py`), 报告给脚本名 + PASS 汇总 + 实测数值,
让下一轮的人(或未来的你)能重跑。改了 spec 就同步改断言, 并在提交信息里写清"这是 spec 变更不是回归"。

### 6. 改"黑盒吃什么"时怎么取证 (模型/执行器的输入面)
用户会直接问「你确定模型用的是不是这张图?」——**读代码回答不算数**, 要有记录。
- **桩件除了替掉黑盒, 还要记录"它被喂了什么"**: 桩 `detector.detect(path, ...)` 把 `path` 追加进列表,
  测试末尾断言"模型吃的是哪张文件"。这是唯一能硬证输入面的手段。
- **面向用户回答用接口字段, 不靠文件名猜**: 让程序把 `model_input` + `model_input_kind` 写进结果 JSON,
  与"人看的图"分字段报出来; 改"人看的图"时模型吃的图与它解耦, 一眼能核。
- 🔴 **不要凭"另一个环境能跑"就改黑盒的输入几何**: 实测同一调用、同一张图, 在 venv 解释器里 **0.7s** 正常返回,
  而在目标机的常驻 app 进程里**卡死**(CPU 空转、几分钟不返回、异步落盘全停、临时文件堆了 90+ 张)。
  换输入尺寸/长宽比/编码前, 必须**在目标机、目标进程里量**(同参、带超时, 同时看副作用: 有没有新文件落盘、
  日志有没有下一阶段输出)—— 只在别的进程里量一遍就上线, 会把目标机的生产通道打死。
- 候选口径用**有界影子**上线, 不要直接替换: 新口径当主判 + 老口径同帧再跑一遍, 只跑 N 张(env 限死、跑完自动停),
  两个结果都进结果 JSON, **判决取并集(任一 NG 即 NG)** ⇒ 试口径期间不漏判; 攒够同帧对照数据再定终局。
  绝不留"默认一直跑"的影子(白耗一倍推理、且会把异常拖成看不到)。

## Pitfalls
- **ctypes 缓冲区只读**: 桩里 `np.frombuffer(bytes(dst))` 赋值会 `ValueError: read-only` → 用 `ctypes.memmove(dst, img.tobytes(), img.size)`。
- **桩件参数形状别猜**: 例如 `SciCam_Payload_ConvertImage(imgAttr, ...)` 第一个参数是 **imgAttr 本身**, 不是
  `payloadAttribute` —— 猜错会 `AttributeError` 停在桩里, 看着像业务 bug。
- **断言写死旧几何**: 输出尺寸/区域范围一变老断言全红 → 先确认是 spec 变了(改断言+提交信息注明),
  别把"我自己改了规格"误报成"程序回退"。
- **端口/通道映射类改动必须用真 HTTP 验**: 只做 `--help`/import 检查会漏掉"请求进来解析不到通道 → 400"。
- **启动前端口自检要带 `SO_REUSEADDR`**, 否则 TIME_WAIT 会被误判成"被占用", 把正常启动拦下。
- **别把"桩件跑通"说成"真机验证过"**: 明确写出哪一段是桩(SDK/模型/执行器)、哪一段是真的(HTTP/几何/落盘/控制律)。
  同理**别把"另一个进程/解释器跑通"当成"目标机没问题"**: 黑盒调用在目标常驻进程里的行为可能完全不同 ⇒ 要单独量。
- **给黑盒的派生输入图用完即删**: 需要额外喂一份图时, 写系统临时目录、调用后立即删——别在产品图片目录里留下
  "第二张图", 现场看到两张图一定会问"这张是哪来的"(只落用户要看的那一张)。

## 配套文件
- `references/image-reading-without-eyes.md` — 看不了图时怎么"读"图: ASCII 降采样 + 逐行/逐列剖面 + 分 run +
  边缘密度判别 + 跨帧一致性(含产线金手指案例真实数字)
- `scripts/ascii_probe.py` — 直接可跑的图像探针: 输出亮度/掩膜 ASCII 图 + 行/列剖面(定边界、判结构)

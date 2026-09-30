---
name: windows-plant-host-operations
description: Use when 给无 SSH 的 Windows 产线机远程上线/停服/交接用户自己调试/取证。
version: 1.0.0
author: Hermes
license: MIT
metadata:
  hermes:
    tags: [windows, plant-host, remote-ops, debugging, forensics, handover]
    related_skills: [zmax-aoi-service, linux-host-maintenance, systemd-boot-services]
---

# 无登录口的 Windows 产线机: 驱动 · 交接 · 取证

## When to Use
- 要在**无 SSH/RDP/WinRM/共享凭据**的 Windows 产线机上上线/停服/重启你维护的程序
- 用户说"我自己在 VSCode 里跑"、"断点怎么没进去"、"结果没更新"(要把在役程序交出去)
- 要判定机器上某张图/某个结果**是真是假**(服务刚卡过、内存帧不可信、模型没检出)
- 你的程序依赖被加密/黑盒的包(pyarmor 等), 断点进不去

适用环境: 产线 Windows 工控机(例: 192.168.23.23, 开 1008x/139/445, **无 SSH/RDP/WinRM/共享凭据**),
上面跑着**你在维护**的程序 + **产线自己的**服务(例: flask_1005 / Mech-Vision)。
具体 AOI 端点/版本口径见用户自有的 `zmax-aoi-service`(要找它自动维护先 `hermes curator adopt`)。

## 铁律(先读, 都是踩过的)

- **它是产线设备**: 只读探针优先; 每次真拍/真停先有理由, 不批量轮询; 不动别人的服务与文件。
- **上线只走部署器**(`tools/aoi_remote_deploy.py` 那类: 拷进静态目录 → 机器 `iwr` 下载 → `Get-FileHash` 逐位核对
  → 备份 `.bak` → 停旧起新 → 验收 → 失败自动回滚)。手工 `iwr -OutFile` **直接覆盖、不留备份** ⇒ 事后再跑一次部署器才有真 `.bak`。
- **版本号放文件头 `VERSION`, 不放文件名**: 上线是**覆盖现场约定名**(`..._v6.py`)。用户在资源管理器/VSCode
  的目录列表里只看到那个约定名 ⇒ 他会以为没有新版(实测被问过"工控机的代码没有 v10 啊")。凡改版都额外 `Copy-Item <约定名> <约定名带版本>` 落一份副本,
  并回报 **VERSION + sha256 + 字节数**(sha 与本地副本逐位相同)。**行号一律按这份报** —— 换版本行号会漂。
- **命令输出用纯 ASCII**: 控制台是 GBK, 中文会乱码 ⇒ 机器上跑的脚本只打印 ASCII key 的 JSON,
  不打印中文。脚本要含中文时先确认编码(或干脆不放中文)。

## 一、驱动它: 反向通道(无登录口时唯一可靠做法)

```bash
./gui-venv311/bin/python tools/station_cmd.py "<PowerShell 一行>"   # 下发并取回执
```
- 回执里 `whoami` = `nt authority\system` ⇒ 计划任务是真跑起来了。
- **单条命令 ~3KB 就会被弄坏**(实测 base64 内嵌 3KB 脚本 ⇒ 变量变空、文件写出 0 字节)
  ⇒ 脚本超 ~1KB 一律**先落到 hub 静态目录**, 再用 `iwr 'http://<本机>:8794/<路径>' -OutFile <文件>` 取。
- PS 5.1: 下载/轮询一律加 `-UseBasicParsing -TimeoutSec 20`(不加会卡在代理/IE 初始化, 看着像"通道死了")。
- 回传命令里**别用 `Write-Host`**(information 流抓不到 ⇒ 只收到空回执), 用管道输出。
- 脚本发下去前本地 `python3 -m py_compile` 过一遍(文档字符串里的 `\x`/`\W` 到机器上会 SyntaxError)。
- **长命令要分片**: 一条命令里带 ≥30s 的 `Start-Sleep`("起服务 + 等它热起来 + 验证"一把梭)经通道走一趟会**回执变空**
  ⇒ 拆成"起"和"等+验证"两条短命令, 每趟只做一件事。
- **下发文件后必须在机器上回读内容**: 静态目录/`iwr -OutFile` 装到的可能还是旧内容 ⇒ 回读并**解析关键字段**
  (例: `(Get-Content <json> -Raw | ConvertFrom-Json).configurations.program`)再报"已生效";
  只比字节数/哈希会把"没生效"当成功报给用户(实测下发后机器上仍是旧配置)。
- 通道健康**看它发来的请求**, 别用日志行数/本机自检判: `sudo timeout 20 tcpdump -A -s 0 -n -i <产线网卡> 'host <机器> and port 8794'`。

## 二、把在役程序**停干净并交给用户自己在 VSCode 里跑**

```powershell
# ① 先看托管任务(分钟级自愈的那种), 必须 Disabled, 否则停完一分钟又被拉起来
Get-ScheduledTask -TaskName 'ZMAX_AOI_KeepAlive' | ForEach-Object { $_.TaskName + ' ' + $_.State }
# ② 只杀自己的程序; 别碰产线自己的 python(flask_/Mech-*)
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -match 'cam_finger|cam_surface' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
# ③ 停干净要**两个证据**: 进程数 0 + 端口无监听
@((Get-NetTCPConnection -LocalPort 10082,10083 -State Listen -EA SilentlyContinue)).Count
```
- VSCode 侧用 `templates/vscode_launch.json`; **`program` 必须写机器上真实存在的部署名**
  (踩过: 配置里写的是没有 `_v6` 的名字 ⇒ F5 直接报找不到程序, 用户以为是程序坏了)。
  **每条通道一条配置, 指向带版本号的副本**(`<约定名>_v12.py`): 在役约定名会被下次上线覆盖, 用户看不出是第几版。
  旧配置先备份(`launch.json.bak_<日期>`), 改完回读字节核验。
- 每个配置带 `PYTHONUNBUFFERED=1` `PYTHONIOENCODING=utf-8` `justMyCode:false`(否则看不到第三方库里的栈)。
- **交还动作一次说清**: 重开任务 + 用与守护一致的方式起进程(见下), 并说明"这段时间这条线没有检测"。
```powershell
# 用 Start-Process + venv 解释器绝对路径(带日志分离):
$p = Start-Process -FilePath 'D:\<dir>\venv\Scripts\python.exe' -ArgumentList '<prog>' `
     -WorkingDirectory 'D:\<dir>' -RedirectStandardOutput 'D:\<dir>\<log>' `
     -RedirectStandardError  'D:\<dir>\<err>' -PassThru
Start-Sleep -Seconds 12; $p.Id; $p.HasExited      # False + 稍后 /storage 200 = 起来了
```
- ⚠️ **起完必须数实例, 只允许 1 个**: `Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -match '<程序名>' }` —— 多实例会**抢独占相机**, 表征是接口 `500 抓帧失败`/`相机初始化失败`;
  两个实例可能跑在**不同解释器**上(venv python + 系统 Python), 用 `ExecutablePath`/`ParentProcessId` 分清
  (app 自己用系统 python 起的子进程 ppid=主进程, 属正常)。实测 `$sh.Run('cmd /c cd /d <dir> && venv\Scripts\python.exe <prog> ...')`
  这种分离启动会留下一个**用系统 Python 跑的影子实例** ⇒ 起之前先杀干净同名进程, 优先用上面的 `Start-Process`。
- ⚠️ 直接 `Stop-Process` 掉在役进程后, 分钟级 keepalive **不一定一轮就拉起来**(实测 75s 未回) ⇒ 手工起一把再验。

## 三、用户说"断点怎么没进去 / 结果没更新": 按序查, 别改代码

1. **断点下在哪个文件**: 断点只在你 `launch.json` 里 `program` 指的那份里生效; 文件不同名 ⇒ VSCode 不当同一模块(灰断点)。
2. **触发方式对不对**: 有副作用的那条路(真检测)与只看一眼的那条路(预览/取帧)往往是两个 HTTP 入口 ——
   预览类常**只拍照不入队** ⇒ 永远不进后台 worker。给用户"干净的触发命令", 并让他先看集成终端有没有阶段日志
   (阶段日志 + 异常 traceback 是最快的判据)。
3. **后台线程是不是活着**(生产者/消费者 + 全局邮箱那类设计): worker 通常在 `__main__` 里就起了 ⇒
   在 `while True:`/取队列那行下断点, 启动后几秒必停。**落结果的那句在 worker 线程里, 不在请求线程** ——
   用户常把断点下在 HTTP 处理函数里, 于是"请求成功但断点不进"。
4. **入队后被跳过**: 代码里常见的 `continue`(输入文件不在就跳过该项)会让断点同样进不去。

## 四、取证纪律: 内存帧 ≠ 落盘文件

- 服务刚卡过/刚重启时, **内存里的"最近一帧"路由会给一张陈旧/雾面帧**(实测同一时刻内存帧底纹标准差 4.08,
  而机器上落盘那张的底纹标准差 21.19) ⇒ 拿它当"图里有什么"的证据, 结论必错。
  判图像内容一律量**落盘文件**: 机器上跑只读探针 `scripts/machine_image_probe.py`
  (尺寸/均值/std/16x16 块内 std/饱和比/列自相关 —— 能区分"真有结构"与"模糊/过曝")。
- **跨图比几何/相关前先核同一帧**: md5 对齐最硬; 跨帧比要写明是跨帧。
- **计数器别混**: 结果接口里的 `n` 多是"成功次数"(可能一直=1), 而帧计数/文件名 `No_<n>` 是"拍照次数"
  (只看一眼也会 +1) —— 两者拿来互相对齐过一次, 白折腾。
- **异步检测的"新旧"必须用计数器判, 不能用固定等待**: 触发接口返回 200 只代表**受理**;
  读结果前先记一次计数 `n0`, 触发后**轮询到 `n` 变化**才算"这一次"的结果 —— 固定 `Start-Sleep N` 再读会把
  **上一次**的判决当本次报出来(表象=用户说"结果不对"); 计数没变就明说是上一次(序号 N)。刚起服务/第一次检测时
  结果接口常回 `404 尚无结果`/500 = "还没有", 不是故障 ⇒ 继续轮询到超时, **别 raise 出去**。
- **耗时按路给预算**: 同一套接口不同通道能差一个量级(实测 1.6s vs 8.7~11.4s) ⇒ 等待/超时按通道分开, 取最慢的乘余量。
- **"模型实际吃了哪张图"要用像素 md5 证明**: 取回"模型输入图"→ `cv2.imdecode` → `md5(ascontiguousarray(img).tobytes())`
  必须 == 结果接口里的 `model_input_md5`; **只看文件名/尺寸不算**。各路口径可能不同(有的路模型吃**同帧派生的另一张**
  且不落盘; 全幅检测那条路模型吃的就是人看的同一张) ⇒ 别把一路的假设搬到另一路。
- **路由/能力结论一律现探再下断言**: `curl -X OPTIONS -D - http://<机器>:<端口><路径>` 看 `Allow:`(零副作用) ——
  历史结论(如"某路只有某个接口")会被后续版本推翻, 照抄给用户就是假情报。
- **交付页面的按钮要真驱动一次**: 用浏览器控制台**执行按钮的 onclick 函数**再读目标元素文本,
  只 curl 服务端 API 通过 ≠ 按钮能用 —— 参数化 id 的前后缀写偏(JS 拼 `x_s`、页面写 `s_x`)会让
  `getElementById` 返 null、函数静默什么都不发生; 加 `if(!el){ alert('缺 #<id>, 请 Ctrl+F5'); return; }` 守卫。
  按钮/面板要带**拍照时间 + 帧龄**和可复制 JSON(用户会把画面/数字当结果, 没有时间基准他没法判新旧)。
- 稳态数据比"峰值/max"可信; 判趋势用窗口平均。

## 五、遇到加密/黑盒依赖(pyarmor 等): 从调用侧做观测

包被 pyarmor 加密时(每个文件第 1 行 `# Pyarmor <版本> ...`, 正文只有 `__pyarmor__(...)`): **内部无源码、断点进不去**。
替代做法: ① 找到调用侧那一行(`detector.detect(...)`)并在那行下断点/记日志;
② 想在**启动前**看内部入参/回报, 在进程里包一层库的公开入口(例: 覆盖 `ultralytics.YOLO.predict`)打点;
③ 参数在**明文 config**(例: `config.yaml` 的 conf/iou/imgsz/device) —— 那才是可调的旋钮;
④ 改在役 config = 动产线配置 ⇒ **先要授权 + 备份 + 同帧复跑, 跑完还原**。

## 六、人眼看得见、模型没检出时怎么分责(缩样)

在机器上用**同一份检测器**对**最新一帧的每种输入**各跑一遍(只读、不占端口):
- 全部 0 ⇒ 不是链路/积压问题, 是模型没检出;
- 再比"人看的那张"与"模型吃的那张"是不是**同一个几何**(常见: 人手看的是自然比例条带,
  模型吃的是被拉伸填成方图的版本 —— 拉伸比因帧而异, 实测有帧纵向 ~15:1 且 40% 像素饱和,
  低对比度缺陷会被插值+饱和吃掉);
- 想分"没看见"与"看见了被阈值卡掉": 降 conf 复跑**同一帧**(先备份 config, 跑完还原)。

## 支持文件

- `templates/vscode_launch.json` —— 交出去自己调试用的 `launch.json`(多套配置 + UTF-8/无缓冲 + `justMyCode:false`)。
- `scripts/machine_image_probe.py` —— 机器上只读量图(尺寸/亮度/std/块内 std/饱和比/列自相关), 可选 `--detect` 跑真模型。
- 相关: `linux-host-maintenance`(本机自检)、`systemd-boot-services`(本机常驻服务)、
  用户自有的 `zmax-aoi-service`(具体 AOI 端点/版本/口径)。

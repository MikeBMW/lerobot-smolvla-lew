# 用 Flask test_client 直测产线程序契约 (无硬件, 2026-09-23 实跑 5/5)

场景: 给**接厂商相机的产线 Flask 程序**改版(如 AOI 表面通道 V2 → V4), 本机没有那台相机/工控机,
但接口语义、几何口径、判决字段都要交付并证明"每档都对"。目标程序是 Flask ⇒ **不必起真服务器**,
`app.test_client()` 直打端点即可, 更快且不会撞端口。

## 配方(四步)

1. **桩模块写文件 + sys.path 前置**(比 `sys.modules[...]` 注入更好读、可复用):
   ```
   _stub/SciCam_class.py          # 相机 SDK: DiscoveryDevices/OpenDevice/Grab/FreePayload…
   _stub/SciCamErrorDefine_const.py   # SCI_CAMERA_OK = 0
   _stub/SciCamInfo_header.py     # SCI_DEVICE_INFO_LIST / gigeInfo.serialNumber = b"D265250099\0"
   _stub/SciCamPayload_header.py  # SCI_CAM_PAYLOAD_ATTRIBUTE / SciCamPixelType / ConvertImage 写回 size
   ```
   `sys.path.insert(0, _stub); sys.path.insert(0, <程序目录>); import <程序模块> as s`
2. **猴补副作用函数**, 把合成帧直接喂进去(比让桩模拟整条抓帧链简单):
   `s.GrabAndSaveImage = fake_grab` / `s.ensure_camera = lambda: True`
   (`fake_grab` 里自己 `cv2.imwrite` 原图 + 规范图, 并写 `s._LAST_CROP_INFO`, 保持与真实现的字段一致)
3. **打端点**: `c = s.app.test_client()`; `c.post("/capture_detect")` / `c.get("/picture?kind=crop")` /
   `c.get("/last_result")` / `c.get("/crop_info")`
4. **断言到内容级**: 图片端点 `cv2.imdecode` 后断**宽高**; JSON 端点断关键字段; 最后汇总 PASS/FAIL 并 `sys.exit(0/1)`

## ⚠️ 最大的坑: test_client 的 SERVER_PORT = 80

程序若按"请求端口 → 模型通道"映射(产线一台机器多通道 10082/10083 的常见写法), 会解析不到通道:

```
① POST /capture_detect → 400 {"msg": "当前通道端口 80 未配置检测模型，可选端口: ['10083']"}
```

这不是业务 bug, 是测试环境的端口。测试里显式补一行(等价于程序 `main()` 启动时注册实际端口):
```python
s.PORT_TO_DETECT_TYPE["80"] = "housing"
```

## 断言清单(实测 5/5 通过, 表面检测 V4)

| # | 请求 | 期望 |
|---|---|---|
| ① | `POST /capture_detect` | 200 `{"code":200,"msg":"success"}`, 且落盘"原图 + 规范图" |
| ② | `GET /picture?kind=crop` | 200 image/png, `cv2.imdecode` → **1280×1280**(保比例 letterbox, 不拉伸) |
| ③ | `GET /picture?kind=origin` | 200, **(2048, 2448)** 原图 |
| ④ | `GET /last_result` | 200, `verdict=NG`, `count=2`, `ms>0`(桩模型投 2 个缺陷) |
| ⑤ | `GET /crop_info` | 200, `canonical=[1280,1280]`, `letterbox_ratio≈0.52`, `imgsz_expected=1280` |

判据要点: ②③ 必须断**宽高**(只断字节数会把"返回 JSON 错误体"当成通过); ⑤ 里 `imgsz_expected`
用来钉住"规范图口径 = 模型 imgsz"这一契约(换模型/改裁剪必须同步)。

## 这个变体覆盖不到的部分(别省真启动)

端口占用自检、参数解析、线程/常驻相机预热、启动顺序(先停旧版) —— 只有 runpy 跑真文件或起真服务才覆盖。
交付话术: 明确写"契约层用 test_client 直测(真 HTTP 语义/几何/字段), 启动链路由现场首启覆盖"。

## 环境准备(避免重装几百 MB)

本机各 venv 可能没有 flask ⇒ 建一个测试专用 venv 并装齐三件套(走镜像):
```bash
cd <程序目录>
<某venv>/bin/python -m venv --system-site-packages .venv-test     # 复用不了别的 venv 的 cv2, 仍需单装
./.venv-test/bin/pip install -q -i https://mirrors.aliyun.com/pypi/simple/ flask opencv-python-headless numpy
./.venv-test/bin/python test_<程序>_offline.py
```

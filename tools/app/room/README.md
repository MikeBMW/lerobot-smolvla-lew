# Z-MAX 现场 APP (com.zmax.room) — 手机装包

老倪 2026-09-27: 「http://<4060>:8791/dl/ZMAX-Site.apk 静静做的这个app, 我装不了, 改好」

## 这里放什么
本目录是 **归档快照**(便于追溯与复现)。**真正在用的工程**在 4060 上:
`/home/ubuntu/state3d_app/room/`  —— 改代码/重打包请在那边改, 再把这三份同步过来。

## 重打包
```bash
bash /home/ubuntu/state3d_app/room/build_room_apk.sh
```
脚本会自动: 编译 → zipalign → **v1+v2+v3 签名** → 验收(v1/v2/v3 + 对齐 + badging)
→ 投递到 `zmax_rel/tools/web/dl/ZMAX-Site.apk`(8791 `/dl/` 服务的唯一目录)
→ 把产物 sha256/体积**写回** `tools/web/room.html` 的安装卡(页面上的校验串因此不会说谎)。

## 手机侧装不上时的实际原因(按可能性排序)
1. **页面根本没给安装入口** —— 原 `room.html` 里一个"装"字样都没有。已加「📲 装 APP」
   卡片(`?inst=1` 可直开), 含下载按钮 + 华为需放开的 3 步 + 报错对照 + 哈希校验。
2. **华为/鸿蒙 纯净模式** —— 开着只允许装应用市场的包; 需 设置→安全→更多安全设置→
   关闭纯净模式 + 允许「安装外部来源应用」。
3. **同包名残留**(应用未安装) —— 先卸载再装; 本版 versionCode=2 正常情况下可直接覆盖。
4. **下载没下完**(解析包错误) —— 用页面上的 sha256 核对。

## 已排除(实测, 别再往这上面查)
- 包本身合格: v1/v2/v3 签名校验全过(`apksigner verify --min-sdk-version 21`)、zipalign 4 字节对齐、
  `resources.arsc` 未压缩、manifest 正确(`exported=true`/targetSdk 34/无 testOnly)。
- **`apksigner verify --verbose` 不带 `--min-sdk-version` 时恒报 `v1: false`** —— 那是"该 minSdk
  不需要 v1", **不是签名残缺**。(曾据此误判一轮, 已在脚本里写明。)
- 服务端下发字节与磁盘源文件 sha256 完全一致(`/dl/` 路由整文件读入 + 正确 Content-Type)。
- 签名 keystore 一直是 `state3d_app/release.keystore`(SHA-256 `86e8d0f0…`), 没有被重新生成过。

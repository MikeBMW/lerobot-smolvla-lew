# 小版本迭代 (VERSION.md 规范 + tools/bump_version.py)

适用于「保存数据, 小版本迭代」「发版」「升级版本号」。**规范真源 = 仓库根的 `VERSION.md`**; 改动只走脚本, 不手改。

## 一条命令 + 6 处同步
```bash
cd /home/ubuntu/zmax
printf '%s' "<一句话: 做了什么 + 根因>" > /tmp/v<新号>.txt
./gui-venv311/bin/python tools/bump_version.py --to <X.Y.Z> --summary-file /tmp/v<新号>.txt --dry   # 先干跑看命中
./gui-venv311/bin/python tools/bump_version.py --to <X.Y.Z> --summary-file /tmp/v<新号>.txt         # 真写(自动 py_compile)
```
脚本负责 5 处 + 1 行历史: studio.py 品牌 QLabel · studio.py 窗口标题(2 处) · studio.py changelog 注释前缀 ·
update_checker.py `CURRENT_VERSION` · docs_sync.py `"version"`+`"zmax_version"` · version_sync.py `zmax_ver`(不带 v) ·
`tools/ci/integrity_check.py` `EXPECTED_VERSION` · `VERSION.md` 版本历史表首行。
语义: 主(架构) · 次(功能模块) · 补丁(修复/小优化); 加工具/修 bug 属**补丁**。

## 干跑判据 (每条必须 旧命中>0 且 新命中>0)
`--dry` 打印 `旧命中 N → 新命中 M ✅`。任何一条 `新命中 0 ❌` = 写回后旧串还在。
**先跑 `--dry` 再真写** —— 这个脚本的病是静默: 匹配不到就什么都不改, 但照旧打印"✅ 已写盘"。

## 坑 (都踩过)
1. **品牌位是双 v (`Z-MAX vv5.16.34`), 不是单 v**。工具若按 `"v"+ver` 拼死串, 则 QLabel/窗口标题/CURRENT_VERSION/docs_sync/integrity
   五处**全部 0 命中且不报错** ⇒ "改了版本等于没改"(只有 VERSION.md 那行变了)。修法 = 认版本号不认记法:
   匹配用 `v{1,2}<ver>` 正则, 写回统一 `vv` 记法。
2. **旧版本号探测别用裸 `Z-MAX v(\d+\.\d+\.\d+)`** —— 会命中 changelog 里的历史串(实测探出 1.0.4) ⇒ 只在
   `QLabel("Z-MAX v{1,2}…")` → 窗口标题 → 兜底 这三档里取, 取众数。
3. `version_sync.py` 的 `zmax_ver` **不带 v**(`"5.16.35"`), 其余品牌位带 `vv` —— 一处口径错就会漏同步。
4. `--from` 显式给上, 别依赖自动探测(探测逻辑本身也会漂)。
5. 版本号只在**下次启动**的窗口标题生效: 已在跑的控制台不会自更新(别为此重启 GUI —— 老倪投诉过反复重启)。

## 收尾(必做)
```bash
./gui-venv311/bin/python tools/ci/integrity_check.py     # 期望: "完整性检查通过: 版本号/功能卡/页面字典/导航/类 五处一致"
# 回读核验 6 处 + VERSION.md 首行, 然后:
git add -A && git commit -m "vv<新号>: <摘要>" && git tag -f vv<新号> -m "Z-MAX vv<新号>"
git push origin main && git push -f origin vv<新号>       # tag 语义: 与品牌同为 vv
```
changelog/VERSION.md 的摘要只写「做了什么 + 根因」, 不写过程; 版本历史表按行追加在**表首**。

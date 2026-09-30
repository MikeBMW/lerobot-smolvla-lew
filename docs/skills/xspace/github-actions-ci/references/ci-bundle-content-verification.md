# 打包产物内容校验 + 外部工件进包 (2026-09-11 实测)

"构建绿" ≠ "包里该有的东西都在"。**把产物内容校验写成 CI 步骤, 缺即 fail** —— 实测踩过两类:
(a) metaworld 的 XML 资产没进 exe → 用户点运行报 `File ...\sawyer_peg_insertion_side.xml does not exist`
+ 无轨迹/无动画; (b) 模型权重在 .gitignore 里 → 打包版 `trained=False`, 只能给随机对照。
两者都是"构建成功、功能静默缺失", 只有内容校验门能拦住。

## 1) 校验包内文件: 按**文件名**匹配, 不要按带路径的串

```yaml
- name: "Verify bundled assets (缺即 fail)"
  shell: bash            # Windows runner 也能用 Git Bash
  run: |
    python -m PyInstaller.utils.cliutils.archive_viewer -r -b tools/gui/dist/App.exe > listing.txt 2>&1 || true
    NM=$(grep -c "metaworld" listing.txt || true)
    NC=$(grep -c "sawyer_peg_insertion_side.xml" listing.txt || true)
    NG=$(grep -c "gen_l4_demo_video.py" listing.txt || true)
    NW=$(grep -c "l4_mani_predictor_v5.pt" listing.txt || true)
    echo "包内: metaworld=$NM · XML=$NC · 生成器=$NG · 权重=$NW"
    grep -m3 "sawyer_peg_insertion_side" listing.txt || true     # 打印样例行, 让 CI 日志自己作证
    if [ "$NC" -lt 1 ] || [ "$NG" -lt 1 ] || [ "$NW" -lt 1 ]; then
      echo "::error::资产未进包"; exit 1
    fi
```

**坑 (实测误报过一次构建失败)**: Windows 归档列表里路径是**反斜杠**
(`metaworld\assets\sawyer_xyz\...`), Linux/mac 是正斜杠 → grep `"assets/sawyer_xyz/xxx.xml"`
在 Windows 恒返回 0 → 明明打进去了却 fail。**只 grep 文件名, 平台无关。**
`-r -b` = 递归 + 只列文件名; onefile 的 exe 也能列出数据文件。
macOS `.app` (onedir) 用 `find App.app -name '*.xml' | wc -l` 更直接 (同样按文件名)。

## 2) gitignore 的外部工件 (模型权重/视频) → CI 下载 + md5 断言 + --add-data + 同一校验门

```yaml
- name: "Download model weights (权重不进库, 走静态站)"
  shell: bash
  run: |
    mkdir -p models
    curl -fsSL -o models/xxx.pt https://<static-host>/models/xxx.pt
    python -c "import hashlib; h=hashlib.md5(open('models/xxx.pt','rb').read()).hexdigest(); \
               print('md5', h); assert h=='<EXPECTED_MD5>', h"
```
- 打包参数: Windows `--add-data "$env:GITHUB_WORKSPACE\models\xxx.pt;models"`, mac `--add-data "$GITHUB_WORKSPACE/models/xxx.pt:models"` (分隔符 `;` vs `:`)
- 上传侧 (人工/脚本): `scp` 到静态目录 → `chmod 644` → **回读 md5 与本地比对** (nginx/PHP 截断历史坑), CI 里断言同一个值
- 该工件必须出现在上面那个校验门里, 否则下次漏打没人知道

## 3) 构建前"生成"的资产必须排在 pyinstaller 之前

`--collect-all <pkg>` 只收**构建那一刻**包目录里存在的文件 ⇒ 需要运行时生成的资产
(例: 把设备几何注入 `metaworld/assets/sawyer_xyz/*_l4.xml`) 必须**先跑生成脚本, 再 pyinstaller**。
步骤顺序就是契约 —— 顺序错了包内就没有, 校验门会拦住 (这正是校验门的价值)。

## 4) Windows 上 `shell: bash` 的脚本别 print emoji

Git Bash (cp1252) 里跑 `python tools/xx.py`, 脚本中 `print("✅ 写入: ...")` 抛
`UnicodeEncodeError: 'charmap' codec can't encode character '\u2705' in position 0` → 步骤 exit 1
(文件其实已写好, 只是日志崩)。修法二选一:
- 脚本顶部: `for _s in (sys.stdout, sys.stderr): _s.reconfigure(encoding="utf-8", errors="replace")`
- 步骤级: `env: { PYTHONIOENCODING: "utf-8" }` (GUI 用 `subprocess(capture_output=True)` 调同一脚本时同理)

## 5) 重跑同一个 tag 的构建 (不新增版本号)

`workflow_dispatch` + `inputs.tag=<已有 tag>`: **checkout 的是触发 ref (通常是 main), tag 输入只决定
Release 上传目标**; `upload-release-action` 的 `overwrite: true` 替换同名资产
⇒ 修好的代码必须在 main 上, 重跑即覆盖旧资产 (不用改 tag 号, 也不用 force-push tag)。
想省一次构建, 也可以直接 `git tag -f` 一个新 tag 让 `on: push: tags` 触发 —— 但优先用 dispatch,
避免动已被用户引用的 tag。

## 6) 自查清单 (发版前)

1. 双平台 job 都 success, 且**校验步骤**绿 (不是只有构建步骤绿)
2. Release 两个资产都在, 大小合理 (新增权重后 exe 应比上版大约 3~5MB)
3. 校验步骤日志里能看到计数 + 样例行 (给用户/自己留证)
4. 生成的 mp4/png 等交付物: 上传到静态站后 curl 200 + 字节数/md5 一致

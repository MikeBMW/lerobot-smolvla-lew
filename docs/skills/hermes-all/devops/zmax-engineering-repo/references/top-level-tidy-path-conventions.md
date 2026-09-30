# 顶层整洁与路径约定 (整理 /home/ubuntu 时的判据)

## 核心判据: 「只搬不删」留下的兼容软链要**复查**, 不是永久保留
迁移时在旧路径留软链是对的; 但**单元/cron/代码随后改指新路径**, 旧软链就变成死链 ——
它在文件管理器里仍显示成一堆 `*.sh` / `*.py`, 看着乱、实则没人调用。
判据(缺一不可):
1. `find <dir> -maxdepth 1 -type f -not -name '.*'` → 顶层**裸文件**应为 0 (有 → 先看是不是软链);
2. 对每条软链查**真调用**(**不看注释/不看历史文档**):
   `grep -rnF '名字' /etc/systemd/system ~/.config/systemd ~/.hermes/{cron,scripts} ~/Desktop ~/.bashrc`
   + 在仓库源码里排除 `docs/ reports/ .git` 后 grep; 命中行是注释/自指不算;
3. 顺带查 `crontab -l`、`.profile`、`*.desktop` 的 `Exec=`。
判为死链 → 删链(`rm`), **目标文件不删**(真身在仓库/数据盘)。删除前写台账(名字 + 原指向)到数据盘 `artifacts/<日期>/`。

## 有功能的小工具要**成对/成套归文件夹**, 别拆散
- 例: `安装Hermes.desktop` 的 `Exec=bash "$(dirname %k)/hermes-restore.sh"` —— **两个文件必须同目录**, 拆开就废。整对放 `~/hermes-install/`。
- 归位后**必须回验**: 语法 `bash -n`、`test -r`、软链能解析; 跑得动的服务 `systemctl is-active` + `systemctl --failed` 计数。

## 模型/权重: 只留数据盘一份, 代码按**解析器**取路径
- 约定: 权重在 `$ZMAX_DATA/models/weights/`; 仓库根与家目录**不许有裸 `.pt`**(ultralytics 会在**当前目录**落下权重 —— 实测就是这么攒出好几份)。
- 反模式: `os.path.join(os.path.dirname(...)×4, "yolov8s.pt")` 这类按 `__file__` 上溯拼家目录路径 —— 迁移后必断, 且删链即坏。
  正解: 写一个解析函数, 顺序 = 环境变量 → 数据盘默认约定 → 仓库根 → 旧路径(遗留兼容), 所有调用点共用 (见 `tools/gui/yolo_perception.py:default_weights_path()`)。
- 改完默认路径后**要真加载验证**(`YoloPerception()` 不给参数 → 打印实际权重路径 + 类别数), 并**重启吃旧码的常驻进程**(否则内存里那份还指向已删路径)。
- 一并核查: 该权重是不是**在役**那个? 例: 在役检测权重是 `models/yolo_peg_live.pt`(软链→fork `runs/detect/.../best.pt`), `yolov8s.pt` 只是没指定 weights 时的 COCO 兜底 —— 别把兜底当成在役。

## 工具本身也会静默失效
`tools/bump_version.py` 按单 `v` 拼字面量, 而品牌早已是双 `v`(`vv5.16.34`) ⇒ 5 处版本号 **0 命中且不报错**(改版本等于没改)。
口径: **认版本号不认记法** —— 匹配用 `v{1,2}X.Y.Z` 正则, 写回用当前品牌记法; 探测旧版本号也走同一条正则(否则会探到 changelog 里的历史字符串)。
凡"同步 N 处"的工具, 改完必须打印**旧命中 → 新命中**计数, 任一处 0 就报错退出。

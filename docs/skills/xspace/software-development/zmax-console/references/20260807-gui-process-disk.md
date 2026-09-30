# GUI 进程管理 + 磁盘铁律 (2026-08-07 实测)

## pkill -f 自匹配自杀 (exit -15)
`pkill -f 'studio.py'` 的命令行 (bash -c "...pkill -f 'studio.py'...") 自身含 "studio.py" → pkill 匹配自己 → 自杀 exit -15 → **可能没杀到目标**。教训:
- 用精确 PID: `kill <pid>` (先 `ps aux | grep '[s]tudio.py'` 拿 PID)
- pkill 模式用 `[s]tudio.py` 正则防自匹配 (grep 技巧同样适用 pgrep/pkill -f)

## 关控制台 vs 保训练 (closeEvent pkill 范围)
studio.py closeEvent 会 `pkill -f "lerobot.scripts.lerobot_train"` + cicd_pipeline → **正常 kill 会连带杀掉后台续训** (独立 bash 脚本起的 lerobot_train 也在模式内)。
- 用户说"关掉控制台"但训练在跑 → **`kill -9 <pid>` 跳过 closeEvent**, 窗口直接消失, 训练保留
- 已知 closeEvent pkill 不覆盖独立脚本 (train_yolo/vla_touch/awe/distill) — 只有 lerobot_train/cicd_pipeline

## 磁盘铁律 (老倪: "磁盘空间绝对不允许增加")
smolvla 系 ckpt 1.4G/个, 4000 步 ≈ 25 个 = 35G/模型。训练/续训链跑完**必须立即**每目录只留最后 ckpt:
```bash
for d in outputs/train/<policy>_*/; do
  ck="$d/checkpoints"; last=$(ls $ck | grep -E '^[0-9]+$' | sort -n | tail -1)
  for c in $(ls $ck | grep -E '^[0-9]+$'); do [ "$c" != "$last" ] && rm -rf "$ck/$c"; done
  [ -e "$ck/last" ] && rm -f "$ck/last"; ln -s "$last" "$ck/last"
done
```
一轮实测 103G→8.9G。重启 GUI 前先确认磁盘 (训练产物是涨盘主因, 不是 GUI)。

## 重启 GUI 的 auto_run 训练触发
- GUI 重启后 auto_run 会触发训练链 (旧行为) → **已改默认不训练**: `ZMAX_AUTO_TRAIN=1` 才触发; auto_run 检测到 lerobot_train 进程也跳过 (busy 保护)
- 曲线文件被训练链启动瞬间清空 → 重启 GUI 前确认没有会触发训练的条件, 曲线 ts 修正为真实训练时间 (见 metaworld-sim-eval)

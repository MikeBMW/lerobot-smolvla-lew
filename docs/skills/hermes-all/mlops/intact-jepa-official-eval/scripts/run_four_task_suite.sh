#!/usr/bin/env bash
# INTACT 四任务 × 3 eval seed × 100 局 · 官方协议全量接力 (无人值守)
#   与 intact_autopilot.sh 同口径: paper_runtime + prior_only (零搜索) + 论文权重 seed3072 分片
#   产物: 逐 seed 结果 json → $OUT/<task>_seed<S>.json | 每局视频 → $VID/<task>_seed<S>/ | showcase + 总表刷新
# 用法: bash run_four_task_suite.sh [tasks] [seeds] [num_eval]
#   默认: "pusht cube reacher tworoom" "0 1 42" 100
set -uo pipefail
R=/home/ubuntu/INTACT-JEPA; PR=$R/paper_runtime
CACHE=/home/ubuntu/stable-wm-cache; OUT=/home/ubuntu/l4_ab/intact_results; VID=$OUT/videos
export VIRTUAL_ENV=$R/.venv PATH=$R/.venv/bin:$PATH
export STABLEWM_HOME=$CACHE LOCAL_DATASET_DIR=$CACHE
export MUJOCO_GL=egl PYOPENGL_PLATFORM=egl CUBLAS_WORKSPACE_CONFIG=:4096:8
export PYTHONPATH="$PR:$R"
TASKS="${1:-pusht cube reacher tworoom}"; SEEDS="${2:-0 1 42}"; NUM="${3:-100}"

# 结果文件名映射 (落 $CACHE/) —— 少一个就会把结果写错地方
declare -A RF=([pusht]=pusht_results.txt [cube]=ogb_cube_results.txt \
               [reacher]=dmc_results.txt [tworoom]=tworoom_results.txt)

# 数据集布局别名 (缺了必然 FileNotFoundError; reacher 必须解析到 datasets/reacher.h5)
mkdir -p "$CACHE/datasets/ogbench" "$CACHE/datasets/dmc"
[ -f "$CACHE/datasets/cube_single_expert.h5" ] && ln -sfn ../cube_single_expert.h5 "$CACHE/datasets/ogbench/cube_single_expert.h5"
[ -f "$CACHE/datasets/reacher.h5" ] && ln -sfn ../reacher.h5 "$CACHE/datasets/dmc/reacher_random.h5"

mkdir -p "$VID"
echo "=== 四任务全量开跑 $(date '+%F %T')  tasks=[$TASKS] seeds=[$SEEDS] num=$NUM ==="
for T in $TASKS; do
  for S in $SEEDS; do
    echo "── $T seed=$S ── $(date '+%H:%M:%S')"
    rm -f "$CACHE"/env_*.mp4                      # env_<i>.mp4 跨运行同名复用, 清掉计数才准
    ( cd "$PR" && timeout 2400 python eval.py --config-name="$T" solver=prior_only \
        policy="recovery_delta_full_${T}_s3072" seed="$S" eval.num_eval="$NUM" \
        output.filename="${RF[$T]}" ) > "$OUT/eval_${T}_seed${S}_$(date +%m%d).log" 2>&1
    rc=$?
    # sidecar json 同名复用 → 跑完立刻拷走
    [ -f "$CACHE/${RF[$T]}.json" ] && cp -f "$CACHE/${RF[$T]}.json" "$OUT/${T}_seed${S}.json"
    sr=$(grep -o "'success_rate': [0-9.]*" "$OUT/eval_${T}_seed${S}_$(date +%m%d).log" | tail -1)
    D="$VID/${T}_seed${S}"; mkdir -p "$D"; rm -f "$D"/*.mp4
    cp -f "$CACHE"/env_*.mp4 "$D"/ 2>/dev/null
    n=$(ls "$D"/*.mp4 2>/dev/null | wc -l)
    echo "   rc=$rc | ${sr:-无结果} | 视频 $n 个 → $D"
    [ "$n" = "0" ] && { echo "   ⚠️ 无视频/无结果 → 立刻看日志尾部:"; tail -6 "$OUT/eval_${T}_seed${S}_$(date +%m%d).log"; }
    # seed42 拼一条「前 6 局连播」便于人眼一次看完
    if [ "$S" = "42" ] && [ "$n" -ge 6 ]; then
      ls "$D"/env_*.mp4 | sort -t_ -k2 -n | head -6 > /tmp/cat_$T.txt
      sed -i "s|^|file '|; s|$|'|" /tmp/cat_$T.txt
      ffmpeg -v error -y -f concat -safe 0 -i /tmp/cat_$T.txt -c copy "$VID/${T}_seed42_showcase.mp4" 2>/dev/null \
        && echo "   showcase → $VID/${T}_seed42_showcase.mp4"
    fi
  done
done
# 复跑/复验的 json 请放 $OUT/recheck_<date>/ 子目录, 否则总表会出现重复列
python3 "$OUT/../intact_summary.py" "$CACHE" "$OUT" >/dev/null 2>&1 && echo "总表已刷新: $OUT/SUMMARY.md"
echo "=== 完成 $(date '+%F %T') ==="; df -h / | tail -1

#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# INTACT-JEPA 本地自主运行流水线 v2 (幂等 / 断点续传 / 无人值守)
#   v2 修正: ① 论文运行时用 PriorOnlySolver(零搜索) 而非根 direct_solver
#            ② 不再传 eval.actor_warmstart (paper 配置无此键 → Hydra KeyError)
#            ③ tworoom 仓库名 lewm-tworooms; ④ 解压后删归档回收磁盘; ⑤ 多 seed(官方 0/1/42)
#   阶段: 环境自检 → 每任务[下载→size+SHA256双核→解压] → 每 seed 官方 Direct 评测 → 汇总
#   用法: bash intact_autopilot.sh [--tasks "pusht tworoom"] [--seeds "0 1 42"] [--num 100]
# ═══════════════════════════════════════════════════════════════════════════════
set -uo pipefail

ROOT=/home/ubuntu/INTACT-JEPA
PR="$ROOT/paper_runtime"
CACHE="${STABLEWM_HOME:-/home/ubuntu/stable-wm-cache}"
DS="$CACHE/datasets"
OUT=/home/ubuntu/l4_ab/intact_results
ASSET=/home/ubuntu/l4_ab/hf_asset.py
LOG="$OUT/autopilot.log"
TASKS="pusht tworoom reacher cube"
SEEDS="0 1 42"
NUM=100
FREE_MIN=80
mkdir -p "$OUT" "$DS"

while [ $# -gt 0 ]; do
  case "$1" in
    --tasks) TASKS="$2"; shift 2;;
    --seeds) SEEDS="$2"; shift 2;;
    --num) NUM="$2"; shift 2;;
    --free-min) FREE_MIN="$2"; shift 2;;
    *) echo "未知参数 $1"; exit 2;;
  esac
done

say() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

# 结果文件名 (各任务不同! 来源: paper_runtime/config/eval/<task>.yaml 的 output.filename)
#   实测踩坑: 用 <task>_results.txt 猜 → reacher 实际写 dmc_results.txt, 导致"未产出结果"误报
result_file() {
  case "$1" in
    pusht)   echo "pusht_results.txt";;
    cube)    echo "ogb_cube_results.txt";;
    reacher) echo "dmc_results.txt";;
    tworoom) echo "tworoom_results.txt";;
    *)       echo "results.txt";;
  esac
}

# 任务元数据: repo|资产文件|解压后目标(相对 $DS)|解压方式|权重目录名|评测任务名
task_meta() {
  case "$1" in
    pusht)   echo "quentinll/lewm-pusht|pusht_expert_train.h5.zst|pusht_expert_train.h5|zst|recovery_delta_full_pusht_s3072|pusht";;
    cube)    echo "quentinll/lewm-cube|cube_single_expert.tar.zst|ogbench/cube_single_expert.h5|tarzst|recovery_delta_full_cube_s3072|cube";;
    reacher) echo "quentinll/lewm-reacher|reacher.tar.zst|dmc/reacher_random.h5|tarzst|recovery_delta_full_reacher_s3072|reacher";;
    tworoom) echo "quentinll/lewm-tworooms|tworoom.tar.zst|tworoom.h5|tarzst|recovery_delta_full_tworoom_s3072|tworoom";;
    *) echo ";;";;
  esac
}

export VIRTUAL_ENV="$ROOT/.venv"
export PATH="$VIRTUAL_ENV/bin:$PATH"
export STABLEWM_HOME="$CACHE" LOCAL_DATASET_DIR="$CACHE"
export MUJOCO_GL="${MUJOCO_GL:-egl}" PYOPENGL_PLATFORM="${PYOPENGL_PLATFORM:-egl}"
export CUBLAS_WORKSPACE_CONFIG="${CUBLAS_WORKSPACE_CONFIG:-:4096:8}"
export PYTHONPATH="$PR:$ROOT"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

say "═══ 流水线 v2 启动 (tasks=[$TASKS] seeds=[$SEEDS] num_eval=$NUM free_min=${FREE_MIN}G) ═══"
say "── 0) 环境自检"
python - <<'PY' 2>&1 | tee -a "$LOG"
import importlib, sys, torch
need = ["torch", "hydra", "omegaconf", "stable_worldmodel", "stable_pretraining", "h5py", "sklearn"]
bad = [m for m in need if not importlib.util.find_spec(m)]
print("   依赖:", "OK" if not bad else f"缺失 {bad}", "| torch", torch.__version__, "cuda", torch.cuda.is_available())
sys.exit(1 if bad else 0)
PY
[ $? -ne 0 ] && { say "❌ 环境不自检 → 中止"; exit 1; }
( cd "$PR" && sha256sum -c RUNTIME_SHA256SUMS >/dev/null 2>&1 ) \
  && say "   评测指纹 OK (paper_runtime 5/5)" || say "   ⚠️ 评测指纹不符"
cp -n "$ROOT/config/eval/solver/direct.yaml" "$PR/config/eval/solver/direct.yaml" 2>/dev/null
[ -f "$PR/config/eval/solver/prior_only.yaml" ] || say "   ⚠️ 缺 PriorOnlySolver 配置"

for T in $TASKS; do
  META=$(task_meta "$T"); [ "$META" = ";;" ] && { say "⚠️ 未知任务 $T"; continue; }
  REPO=${META%%|*}; R1=${META#*|}; FILE=${R1%%|*}; R2=${R1#*|}
  TARGET=${R2%%|*}; R3=${R2#*|}; XMODE=${R3%%|*}; R4=${R3#*|}
  POLICY=${R4%%|*}; ETASK=${R4#*|}

  # 已全部 seed 完毕 → 只补数据, 不重跑评测
  #   ★ 踩坑: 曾经在这里直接 continue → 结果齐时想用 --seeds 0 补数据集, 结果连数据也没下
  DONE=1; for S in $SEEDS; do [ -f "$OUT/${T}_seed${S}.json" ] || DONE=0; done
  [ "$DONE" = "1" ] && say "  ℹ️ $T 评测结果已齐 → 仅做数据就位 (不重跑评测)"
  say "══════ 任务 $T (repo=$REPO file=$FILE) ══════"

  # 1) 数据集
  if [ -f "$DS/$TARGET" ]; then
    say "  ⏭ 数据集已在位: $DS/$TARGET"
  else
    # 1a) 布局别名: 归档内容与评测期望路径名不一致时用符号链接接上 (不复制 GB 级数据)
    #     实测: reacher.tar.zst 解出 datasets/reacher.h5, 而 eval 配置 dataset_name=dmc/reacher_random
    case "$T" in
      reacher) if [ -f "$DS/reacher.h5" ]; then
                 mkdir -p "$DS/dmc"; ln -sfn ../reacher.h5 "$DS/dmc/reacher_random.h5"
                 say "  🔗 布局别名: dmc/reacher_random.h5 -> ../reacher.h5"; fi;;
      # ★ 2026-09-12 实测: cube_single_expert.tar.zst 解出的 h5 在 datasets/ 根, 而评测期望
      #   datasets/ogbench/cube_single_expert.h5 → 上一轮"解压后未见"导致 101GB 数据白解+归档没删
      cube) if [ -f "$DS/cube_single_expert.h5" ]; then
              mkdir -p "$DS/ogbench"; ln -sfn ../cube_single_expert.h5 "$DS/ogbench/cube_single_expert.h5"
              say "  🔗 布局别名: ogbench/cube_single_expert.h5 -> ../cube_single_expert.h5"; fi;;
    esac
  fi
  if [ -f "$DS/$TARGET" ]; then
    say "  ⏭ 数据集已在位: $DS/$TARGET"
  else
    read -r ASIZE ASHA < <(python3 "$ASSET" meta "$REPO" "$FILE")
    if [ -z "${ASIZE:-}" ] || [ "$ASIZE" = "NOT_FOUND" ] || [ "$ASIZE" = "NO_HASH" ]; then
      say "  ❌ 取不到资产元数据 ($REPO/$FILE) → 跳过"; continue
    fi
    NEED_GB=$(( ASIZE * 26 / 10000000000 + 15 ))
    FREE_GB=$(df --output=avail -BG /home | tail -1 | tr -dc '0-9')
    say "  资产 $(( ASIZE/1000000000 ))GB (sha256=${ASHA:0:12}…) 需≈${NEED_GB}GB, 现有 ${FREE_GB}GB"
    if [ "$FREE_GB" -lt "$NEED_GB" ] || [ "$FREE_GB" -lt "$FREE_MIN" ]; then
      say "  ⛔ 磁盘不足 (需 ${NEED_GB}GB / 红线 ${FREE_MIN}GB, 实 ${FREE_GB}GB) → 跳过 $T (诚实记录)"; continue
    fi
    URL=$(python3 "$ASSET" url "$REPO" "$FILE")
    say "  ⬇ $URL"
    aria2c -x 16 -s 16 -k 1M -c --file-allocation=none --max-tries=0 --retry-wait=10 \
           --summary-interval=60 --console-log-level=warn -d "$DS" -o "$FILE" "$URL" \
           >> "$OUT/aria2_${T}.log" 2>&1
    [ $? -ne 0 ] && { say "  ❌ aria2 退出码非 0 (可重跑续传)"; continue; }
    RSIZE=$(stat -c%s "$DS/$FILE")
    [ "$RSIZE" != "$ASIZE" ] && { say "  ❌ 大小不符 $RSIZE != $ASIZE"; continue; }
    V=$(python3 "$ASSET" verify "$DS/$FILE" "$ASHA")
    [ "$V" != "OK" ] && { say "  ❌ SHA256 校验失败 ($V)"; continue; }
    say "  ✅ 归档双核通过 (size+sha256)"
    case "$XMODE" in
      zst)    zstd -d -T0 -f "$DS/$FILE" -o "$DS/$TARGET" >>"$LOG" 2>&1 || { say "  ❌ zstd 解压失败"; continue; } ;;
      tarzst) tar --zstd -xf "$DS/$FILE" -C "$DS" >>"$LOG" 2>&1 || { say "  ❌ tar 解压失败"; continue; } ;;
    esac
    [ ! -f "$DS/$TARGET" ] && { say "  ⚠️ 解压后未见 $DS/$TARGET:"; find "$DS" -maxdepth 2 -type f -newermt '-20 minutes' | head -6 | tee -a "$LOG"; continue; }
    say "  ✅ 解压完成 $(stat -c%s "$DS/$TARGET") 字节 → 删归档回收磁盘"
    rm -f "$DS/$FILE"
  fi

  # 2) 每 seed 评测 (结果齐则整段跳过; 数据已在上一步就位)
  if [ "$DONE" = "1" ]; then
    say "  ⏭ 跳过评测 (结果已齐); 数据集保留以便 VSCode 手动调试"
  else
  for S in $SEEDS; do
    if [ -f "$OUT/${T}_seed${S}.json" ]; then say "  ⏭ $T seed$S 已有结果"; continue; fi
    say "  ── $T seed=$S: preflight"
    bash "$ROOT/scripts/eval_direct.sh" --preflight-only "$ETASK" "$POLICY" "$S" 2>&1 | grep -E "FINAL|FAIL" | tee -a "$LOG"
    say "  ── $T seed=$S: 官方 Direct 评测 (PriorOnlySolver 零搜索)"
    ( cd "$PR" && python eval.py --config-name="$ETASK" solver=prior_only policy="$POLICY" \
        seed="$S" eval.num_eval="$NUM" ) > "$OUT/eval_${T}_seed${S}.log" 2>&1
    RF=$(result_file "$ETASK")
    if [ -f "$CACHE/${RF}.json" ]; then
      cp -f "$CACHE/${RF}.json" "$OUT/${T}_seed${S}.json"
      say "  ✅ $T seed$S → $OUT/${T}_seed${S}.json"
    else
      say "  ❌ $T seed$S 未产出结果:"; tail -4 "$OUT/eval_${T}_seed${S}.log" | tee -a "$LOG"
    fi
  done
  fi
  # 3) 结果齐 → 回收该任务大数据集 (★ 改为**显式** RECLAIM=1 才回收: 默认保留, 便于 VSCode 手动调试)
  DONE2=1; for S in $SEEDS; do [ -f "$OUT/${T}_seed${S}.json" ] || DONE2=0; done
  if [ "$DONE2" = "1" ] && [ "${RECLAIM:-0}" = "1" ]; then
    if [ -f "$DS/$TARGET" ] && [ ! -L "$DS/$TARGET" ]; then
      SZ=$(stat -c%s "$DS/$TARGET")
      rm -f "$DS/$TARGET"; rm -f "$DS/$FILE"
      say "  ♻️ 结果已齐 → 回收数据集 $TARGET ($(( SZ/1000000000 ))GB) 与归档; 磁盘 $(df --output=avail -BG /home | tail -1 | tr -dc '0-9')GB 可用"
    fi
  fi
done

say "═══ 汇总 ═══"
python3 /home/ubuntu/l4_ab/intact_summary.py "$CACHE" "$OUT" 2>&1 | tee -a "$LOG"
say "═══ 流水线结束 ═══"

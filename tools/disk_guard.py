#!/usr/bin/env python3
"""Z-MAX 数据容量守卫 · 上限控制 (防磁盘充满)
策略:
  - orin_live 采集包: 保留最近 60 个 (约30MB)
  - orin_hd_cache: 清空 (临时缓存)
  - outputs/train: 保留最近 4 个训练产物
  - loop_train.log: 保留 5MB
  - dds_flow 时间序列: 保留最近 2 万行 (每10s一条≈2.3天)
  - /tmp 临时文件: 清 7 天前的
用法: python3 tools/disk_guard.py [--once]
"""
import os, glob, time, sqlite3, shutil
from pathlib import Path

HOME = Path.home() / "lerobot-smolvla-lew"
DDS_DB = Path.home() / "zmax-website" / "dds.db"
TRAIN = HOME / "outputs" / "train"
LIVE = HOME / "data" / "orin_live"
HD_CACHE = HOME / "data" / "orin_hd_cache"
LOOP_LOG = TRAIN / "loop_train.log"

LIMITS = {
    "orin_live_pkgs": 60,      # 采集包保留数
    "train_dirs": 4,           # 训练产物保留数
    "loop_log_mb": 5,          # 训练日志上限
    "dds_flow_rows": 20000,    # 水流序列上限
    "tmp_age_days": 7,         # /tmp 清理年龄
}


def clean_orin_live():
    """采集包: 保留最近 N 个"""
    pkgs = sorted(glob.glob(str(LIVE / "*.json")), key=os.path.getmtime)
    rm = pkgs[:-LIMITS["orin_live_pkgs"]] if len(pkgs) > LIMITS["orin_live_pkgs"] else []
    for f in rm:
        os.remove(f)
    return len(rm), len(pkgs)


def clean_hd_cache():
    """高清缓存: 清空"""
    n = 0
    if HD_CACHE.exists():
        for f in HD_CACHE.glob("*.jpg"):
            f.unlink(missing_ok=True)
            n += 1
    return n


def clean_train():
    """训练产物: 保留最近 N 个"""
    dirs = sorted([d for d in TRAIN.glob("act_*") if d.is_dir()], key=os.path.getmtime)
    rm = dirs[:-LIMITS["train_dirs"]] if len(dirs) > LIMITS["train_dirs"] else []
    total = 0
    for d in rm:
        sz = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
        shutil.rmtree(d, ignore_errors=True)
        total += sz
    return len(rm), total // 1024 // 1024


def clean_log():
    """训练日志: 超限截断保留尾部"""
    if LOOP_LOG.exists() and LOOP_LOG.stat().st_size > LIMITS["loop_log_mb"] * 1024 * 1024:
        data = LOOP_LOG.read_text(encoding="utf-8", errors="ignore")
        keep = data[-LIMITS["loop_log_mb"] * 1024 * 1024:]
        LOOP_LOG.write_text("…(截断)…\n" + keep)
        return True
    return False


def clean_dds_flow():
    """水流序列: 保留最近 N 行"""
    try:
        db = sqlite3.connect(DDS_DB)
        c = db.cursor()
        c.execute("DELETE FROM dds_flow WHERE id NOT IN (SELECT id FROM dds_flow ORDER BY id DESC LIMIT ?)",
                  (LIMITS["dds_flow_rows"],))
        db.commit()
        n = c.execute("SELECT COUNT(*) FROM dds_flow").fetchone()[0]
        db.close()
        return n
    except Exception as ex:
        print(f"  ⚠️ dds_flow: {ex}")
        return -1


def clean_tmp():
    """/tmp 清理 7 天前的"""
    n = 0
    now = time.time()
    for f in glob.glob("/tmp/*"):
        try:
            if os.path.isfile(f) and now - os.path.getmtime(f) > LIMITS["tmp_age_days"] * 86400:
                os.remove(f)
                n += 1
        except Exception:
            pass
    return n


def main():
    once = "--once" in sys.argv
    print("🛡️ 容量守卫启动 (每次运行自动清理)")
    while True:
        try:
            n1, tot1 = clean_orin_live()
            n2 = clean_hd_cache()
            n3, mb3 = clean_train()
            n4 = clean_log()
            n5 = clean_dds_flow()
            n6 = clean_tmp()
            print(f"[{time.strftime('%H:%M:%S')}] 清理: 采集-{n1}/{tot1} · 缓存-{n2} · 训练-{n3}({mb3}MB) · 日志-{n4} · 水流-{n5}行 · tmp-{n6}")
        except Exception as ex:
            print(f"⚠️ {ex}")
        if once:
            break
        time.sleep(3600)  # 每小时


if __name__ == "__main__":
    import sys
    main()

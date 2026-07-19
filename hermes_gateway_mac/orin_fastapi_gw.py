#!/usr/bin/env python3
"""Orin Gateway — 数据+录制+下载"""
import json, time, os, re, subprocess, signal, glob, io, tarfile
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import uvicorn

app = FastAPI(title="Orin Gateway")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

JOINT_FILE = "/tmp/joints.json"
PORT = 8765
RECORD_PROC = None


# ─── 健康 ───
@app.get("/health")
def get_health():
    return {"online": True, "ts": time.time()}


# ─── 关节 ───
@app.get("/joints")
def get_joints():
    try:
        raw = open(JOINT_FILE).read().strip()
        vals = []
        for v in raw.split(","):
            v = v.strip().lstrip("- ")
            try: vals.append(round(float(v), 4))
            except: pass
        return {"joints": vals[:6], "ts": time.time()}
    except:
        return {"joints": [], "ts": 0}


# ─── 录制控制 ───
@app.post("/record/start")
def record_start(duration: int = 30):
    global RECORD_PROC
    if RECORD_PROC and RECORD_PROC.poll() is None:
        return {"status": "error", "message": "already recording"}
    ts = int(time.time())
    out = f"/tmp/zmax_{ts}"
    cmd = f'bash -c \'source /opt/ros/humble/setup.bash && source /home/tashan/07151/tashan_robot_so_20260715_145343_07f342b_aarch64/install/setup.bash && export ROS_DOMAIN_ID=23 && timeout {duration + 5} ros2 bag record -o {out} --max-bag-duration {duration} -a\''
    RECORD_PROC = subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"status": "recording", "out": out, "duration": duration, "pid": RECORD_PROC.pid}


@app.post("/record/stop")
def record_stop():
    global RECORD_PROC
    if RECORD_PROC and RECORD_PROC.poll() is None:
        RECORD_PROC.terminate()
        try: RECORD_PROC.wait(5)
        except: RECORD_PROC.kill()
        return {"status": "stopped"}
    return {"status": "idle"}


@app.get("/record/status")
def record_status():
    global RECORD_PROC
    if RECORD_PROC and RECORD_PROC.poll() is None:
        return {"recording": True, "pid": RECORD_PROC.pid}
    return {"recording": False}


# ─── 最新录制信息 ───
@app.get("/record/latest")
def record_latest():
    dirs = sorted(glob.glob("/tmp/zmax_*"), key=os.path.getmtime, reverse=True)
    if not dirs:
        return {"error": "no recordings"}
    d = dirs[0]
    name = os.path.basename(d)
    size_mb = round(sum(os.path.getsize(f) for f in glob.glob(f"{d}/*") if os.path.isfile(f)) / 1048576, 1)
    return {"dir": d, "name": name, "size_mb": size_mb}


# ─── 下载最新录制 ───
@app.get("/record/download")
def record_download():
    dirs = sorted(glob.glob("/tmp/zmax_*"), key=os.path.getmtime, reverse=True)
    if not dirs:
        return {"error": "no recordings"}
    d = dirs[0]

    def iter_tar():
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for f in glob.glob(f"{d}/**", recursive=True):
                if os.path.isfile(f):
                    tar.add(f, arcname=os.path.relpath(f, os.path.dirname(d)))
        buf.seek(0)
        yield from buf

    name = os.path.basename(d)
    return StreamingResponse(
        iter_tar(), media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{name}.tar.gz"'}
    )

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")


# ─── 磁盘监控 ───
@app.get("/disk")
def get_disk():
    dirs = sorted(glob.glob("/tmp/zmax_*"), key=os.path.getmtime)
    total_mb = 0
    oldest = None
    for d in dirs:
        s = sum(os.path.getsize(f) for f in glob.glob(f"{d}/*") if os.path.isfile(f))
        total_mb += s
        if oldest is None:
            oldest = {"dir": d, "size_mb": round(s / 1048576, 1)}
    return {
        "total_mb": round(total_mb / 1048576, 1),
        "count": len(dirs),
        "over_1g": total_mb > 1048576000,
        "oldest": oldest
    }


# ─── 清理旧数据 ───
@app.post("/record/cleanup")
def cleanup(n: int = 10):
    """保留最新的n个录制，删除旧的"""
    dirs = sorted(glob.glob("/tmp/zmax_*"), key=os.path.getmtime)
    if len(dirs) <= n:
        return {"deleted": 0, "remaining": len(dirs)}
    deleted = 0
    freed_mb = 0
    for d in dirs[:-n]:
        s = sum(os.path.getsize(f) for f in glob.glob(f"{d}/*") if os.path.isfile(f))
        freed_mb += s
        import shutil
        shutil.rmtree(d, ignore_errors=True)
        deleted += 1
    return {"deleted": deleted, "freed_mb": round(freed_mb / 1048576, 1), "remaining": n}

#!/usr/bin/env python3
"""
Orin MCAP 数据服务
POST /record  → 录制 ROS2 bag (MCAP格式)
GET  /download → 下载 bag 文件
GET  /status   → 当前状态
"""
from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import FileResponse
import subprocess, os, time, json, glob

app = FastAPI(title="Z-MAX MCAP Service")
RECORD_DIR = "/tmp/zmax_bags"
os.makedirs(RECORD_DIR, exist_ok=True)

_current = {"recording": False, "file": None, "topics": []}
_ros2_env = (
    "source /opt/ros/humble/setup.bash && "
    "source ~/0615/tashan_robot_so_20260630_163849_f98c30a_aarch64/install/setup.bash && "
    "export ROS_DOMAIN_ID=23"
)

@app.get("/status")
def status():
    bags = sorted(glob.glob(f"{RECORD_DIR}/*"), key=os.path.getmtime, reverse=True)
    return {
        "recording": _current["recording"],
        "current_file": _current["file"],
        "bags": [{"name": os.path.basename(b), "size_mb": round(os.path.getsize(b)/1e6,2)} for b in bags[:5]]
    }

@app.post("/record")
def start_record(duration: int = 60, topics: str = "/real_joint_states,/robot/force_torque,/gripper_pos,/robot/tcp_pose,/robot_status"):
    if _current["recording"]:
        return {"error": "already recording"}
    name = f"zmax_{time.strftime('%Y%m%d_%H%M%S')}"
    path = os.path.join(RECORD_DIR, name)
    tlist = topics.split(",")
    _current["recording"] = True
    _current["file"] = name
    _current["topics"] = tlist
    
    def _record():
        subprocess.run([
            "bash", "-c",
            f"{_ros2_env} && ros2 bag record -o {path} --max-bag-duration {duration} " + " ".join(tlist)
        ], timeout=duration + 20)
        _current["recording"] = False
    
    import threading
    threading.Thread(target=_record, daemon=True).start()
    return {"status": "recording", "file": name, "duration": duration, "topics": tlist}

@app.get("/download/{filename}")
def download(filename: str):
    path = os.path.join(RECORD_DIR, filename)
    if not os.path.exists(path):
        # if it's a directory, zip it
        if os.path.isdir(os.path.join(RECORD_DIR, filename)):
            import zipfile
            zip_path = path + ".zip"
            with zipfile.ZipFile(zip_path, 'w') as zf:
                for root, dirs, files in os.walk(path):
                    for f in files:
                        zf.write(os.path.join(root, f), f)
            return FileResponse(zip_path, filename=filename + ".zip")
        return {"error": "not found"}
    return FileResponse(path, filename=filename)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8765)

import sys, json
sys.path.insert(0,"/sdk")
import xcoresdk_python as x
r=x.xMateRobot(); r.connectToRobot("192.168.23.160")
def dump(o):
    d={}
    for n in dir(o):
        if n.startswith("_"): continue
        try:
            v=getattr(o,n)
            if callable(v): continue
            d[n]= v if isinstance(v,(str,int,float,bool,list)) else str(v)[:120]
        except Exception: pass
    return d
logs=r.queryControllerLog(40,{x.LogInfoLevel.error}, {})
print("错误级日志", len(logs), "条:")
for L in logs[:20]:
    print("  ", json.dumps(dump(L), ensure_ascii=False)[:260])
w=r.queryControllerLog(15,{x.LogInfoLevel.warning}, {})
print("警告级日志", len(w), "条 (前 8):")
for L in w[:8]:
    print("  ", json.dumps(dump(L), ensure_ascii=False)[:240])
r.disconnectFromRobot({})

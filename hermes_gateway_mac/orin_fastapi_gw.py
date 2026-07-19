#!/usr/bin/env python3
"""Orin Gateway — 读/tmp/joints.json 提供 HTTP API"""
import json, time, os, re
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI(title="Orin Gateway")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

JOINT_FILE = "/tmp/joints.json"
PORT = 8765

@app.get("/joints")
def joints():
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

@app.get("/health")
def get_health():
    return {"online": True, "ts": time.time()}

uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")

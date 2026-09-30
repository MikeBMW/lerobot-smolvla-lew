@echo off
chcp 65001 >nul
title Create GPU Docker Container (hermes-ubuntu-gpu2)
echo ============================================================
echo   Create GPU Docker Container: hermes-ubuntu-gpu2
echo   Image: ubuntu:24.04  GPU: --gpus all
echo   Mount: D:\hermes-docker\.hermes -^> /root/.hermes
echo          D:\hermes-docker\workspace -^> /workspace
echo   Step 4 installs full training env (restore.sh: repo + venv + torch CUDA)
echo ============================================================
echo.

REM ---- 1. Check Docker Desktop ----
echo [1/4] Checking Docker Desktop ...
docker version >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Docker Desktop is NOT running. Start it first, then double-click this again.
  pause
  exit /b 1
)
echo [OK] Docker is running
echo.

REM ---- 2. Check NVIDIA driver on Windows ----
echo [2/4] Checking NVIDIA driver ...
nvidia-smi >nul 2>&1
if errorlevel 1 (
  echo [ERROR] NVIDIA driver not found on Windows. Install it first.
  pause
  exit /b 1
)
for /f "delims=" %%i in ('nvidia-smi --query-gpu=name --format=csv,noheader') do set GPUNAME=%%i
echo [OK] GPU found: %GPUNAME%
echo.

REM ---- 3. Create GPU container ----
echo [3/4] Creating container hermes-ubuntu-gpu2 ...
docker rm -f hermes-ubuntu-gpu2 >nul 2>&1
docker run -d --name hermes-ubuntu-gpu2 --gpus all ^
  -v "D:\hermes-docker\.hermes:/root/.hermes" ^
  -v "D:\hermes-docker\workspace:/workspace" ^
  --shm-size=2g ^
  ubuntu:24.04 sleep infinity
if errorlevel 1 (
  echo [ERROR] Container creation FAILED.
  echo   Likely cause: Docker Desktop GPU support not enabled.
  echo   Fix: Docker Desktop -^> Settings -^> Resources -^> WSL Integration (GPU passthrough)
  docker run --rm --gpus all ubuntu:24.04 ls /dev/ ^| findstr nvidia
  pause
  exit /b 1
)
echo [OK] Container created
echo.

REM ---- 4. Install full training env + verify GPU ----
echo [4/4] Installing training env (restore.sh) ...
echo       This takes 10-20 minutes (torch 2GB+ download), please wait ...
docker exec hermes-ubuntu-gpu2 bash -c "bash /root/.hermes/backup/restore.sh" 2>&1 | findstr /v "^$"

echo.
echo ============================================================
echo  FINAL GPU CHECK:
echo ============================================================
docker exec hermes-ubuntu-gpu2 bash -c "/root/gui-venv311/bin/python -c 'import torch; print(\"torch\", torch.__version__, \"| CUDA:\", torch.cuda.is_available(), \"|\", torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"NO GPU\")'"
echo.
echo  DONE!
echo  Enter container (Windows Terminal or CMD):
echo    docker exec -it hermes-ubuntu-gpu2 bash
echo  Or: Docker Desktop -^> Containers -^> hermes-ubuntu-gpu2 -^> terminal
echo ============================================================
pause

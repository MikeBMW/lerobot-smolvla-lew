# Z-MAX Console — Lightweight Docker image (PyQt5 + X11 host socket)
# Usage:
#   docker build -t zmax-console tools/gui/
#   docker run --rm -e DISPLAY=$DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix \
#       -v /home/xspace/.hermes:/home/xspace/.hermes:ro \
#       zmax-console

FROM python:3.12-slim

# Qt/X11 runtime deps (minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxcb-xinerama0 \
    libxkbcommon-x11-0 \
    libgl1-mesa-glx \
    libegl1-mesa \
    libdbus-1-3 \
    fontconfig \
    && rm -rf /var/lib/apt/lists/*

# LeRobot & CLI modules (for training_backend.py subprocess calls)
RUN pip install --no-cache-dir \
    PyQt5 \
    numpy \
    pillow

# Create non-root user matching host uid
ARG UID=1000
ARG GID=1000
RUN groupadd -g $GID xspace && useradd -m -u $UID -g $GID xspace
USER xspace
WORKDIR /home/xspace

# Copy the console code
COPY --chown=xspace:xspace . /home/xspace/console/

# Entry: studio.py (full console) or le_robot_studio.py (lightweight)
# Accept CMD override: "studio" (default) or "simple"
ENV CONSOLE_MODE=studio
CMD ["sh", "-c", "cd /home/xspace/console && python3 ${CONSOLE_MODE}.py"]

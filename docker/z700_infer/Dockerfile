# Z700 整体部署镜像 — 模型进 docker, 部署到 Mac M1 (arm64)
# 构建: 在 Mac 上 docker build (原生 arm64, 无需 QEMU 交叉)
#   用法:
#     curl -o z700_models.tar.gz <ECS包URL>   # 或 cicd_pull_z700.py pull
#     tar xzf z700_models.tar.gz -C models/
#     docker build -t z700-infer .
#     docker run -d -p 8001:8001 --name z700-infer z700-infer
# 推理 API: /health /detect /predict (见 infer_service.py)
FROM arm64v8/python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

# 系统依赖 (opencv 需要 libgl)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖 (CPU 推理, Mac M1 无 CUDA; torch arm64 官方 wheel)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 模型与配置 (整体迁移: YOLO + 双脑 + 状态机)
COPY models/ ./models/
COPY infer_service.py .

EXPOSE 8001
CMD ["uvicorn", "infer_service:app", "--host", "0.0.0.0", "--port", "8001"]

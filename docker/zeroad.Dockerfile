# Tooling image for reading 0 A.D. data: git with LFS, Python, Pillow.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git git-lfs ca-certificates \
    && git lfs install --system && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir pyyaml==6.0.2 pillow==11.0.0
RUN git config --system --add safe.directory '*'

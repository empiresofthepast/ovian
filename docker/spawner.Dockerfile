# The world spawner: the docker CLI with compose, plus a small FastAPI app (server/src/ovian_spawner).
FROM docker:27-cli
RUN apk add --no-cache python3 py3-pip \
 && pip install --no-cache-dir --break-system-packages "fastapi~=0.115" "uvicorn~=0.32" "asyncpg~=0.30" "pyyaml~=6.0" "pydantic~=2.9"
COPY server/src/ovian_spawner /app/ovian_spawner
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["python3", "-m", "uvicorn", "ovian_spawner.app:app", "--host", "0.0.0.0", "--port", "8000"]

# AI rulers: NPC kingdoms that play Ovian through the public HTTP API.
FROM python:3.12-slim-bookworm
RUN pip install --no-cache-dir "httpx>=0.27,<1"
WORKDIR /app
COPY ovian_bots.py .
USER nobody
ENV PYTHONUNBUFFERED=1
CMD ["python", "ovian_bots.py"]

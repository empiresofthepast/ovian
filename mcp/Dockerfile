# MCP server: lets AI assistants run a player's cities through the public API.
FROM python:3.12-slim-bookworm
RUN pip install --no-cache-dir "mcp>=1.20,<2" "httpx>=0.27,<1"
WORKDIR /app
COPY ovian_mcp.py .
USER nobody
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["python", "ovian_mcp.py"]

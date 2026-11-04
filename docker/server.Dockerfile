# syntax=docker/dockerfile:1.6
# Build context: repository root.

# ---- build the Rust engine wheel and the server wheel ----
FROM python:3.12-slim-bookworm AS wheels
COPY --from=rust:1-slim-bookworm /usr/local/cargo /usr/local/cargo
COPY --from=rust:1-slim-bookworm /usr/local/rustup /usr/local/rustup
ENV PATH=/usr/local/cargo/bin:$PATH RUSTUP_HOME=/usr/local/rustup CARGO_HOME=/usr/local/cargo
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir "maturin>=1.7,<2"
WORKDIR /build
COPY engine engine
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/build/engine/target \
    cd engine/crates/ovian-py && maturin build --release -o /wheels
COPY server server
RUN pip wheel --no-cache-dir --no-deps -w /wheels ./server

# ---- runtime ----
FROM python:3.12-slim-bookworm AS runtime
RUN useradd --system --uid 10001 ovian
COPY --from=wheels /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels
COPY content /app/content
WORKDIR /app
ENV OVIAN_CONTENT_DIR=/app/content/classic PYTHONUNBUFFERED=1
USER ovian
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["ovian-server"]

# ---- tests (docker compose -f docker-compose.test.yml run --rm server-tests) ----
FROM runtime AS test
USER root
RUN pip install --no-cache-dir "pytest>=8" "pytest-asyncio>=0.24" "httpx>=0.27"
COPY server/pyproject.toml /app/server/pyproject.toml
COPY server/tests /app/server/tests
WORKDIR /app/server
USER ovian
CMD ["pytest", "-q", "-p", "no:cacheprovider"]

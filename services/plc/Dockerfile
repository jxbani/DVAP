# Build context is the repo root (see docker-compose.yml).
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY dvap_common ./dvap_common
COPY services/plc/plc ./plc
ENV PATH="/app/.venv/bin:$PATH"
# 502 Modbus/TCP, 4840 OPC UA, 8000 /health. None are published to the host.
CMD ["uvicorn", "plc.main:app", "--host", "0.0.0.0", "--port", "8000"]

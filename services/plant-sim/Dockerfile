# Build context is the repo root (see docker-compose.yml).
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY dvap_common ./dvap_common
COPY services/plant-sim/plant_sim ./plant_sim
ENV PATH="/app/.venv/bin:$PATH"
CMD ["uvicorn", "plant_sim.api:app", "--host", "0.0.0.0", "--port", "8000"]

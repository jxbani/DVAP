# One image recipe for every Python service. Build context is the repo root.
# docker-compose.yml picks the service with build args, e.g. SERVICE=plant-sim PACKAGE=plant_sim.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
COPY pyproject.toml uv.lock ./
# --locked: install exactly the versions and hashes in uv.lock, and fail if it is out of date.
# --no-install-project: the containers run the services by pythonpath and never need the `dvap`
# CLI package (bench/), which isn't copied here. It is built only locally by `uv run dvap`.
RUN uv sync --locked --no-dev --no-install-project
COPY dvap_common ./dvap_common
ARG SERVICE
ARG PACKAGE
ARG MODULE=api
COPY services/${SERVICE}/${PACKAGE} ./${PACKAGE}
ENV PATH="/app/.venv/bin:$PATH" APP="${PACKAGE}.${MODULE}:app"
# Every service serves HTTP (at least /health) on 8000 inside the docker network.
CMD ["sh", "-c", "exec uvicorn $APP --host 0.0.0.0 --port 8000"]

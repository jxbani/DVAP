.PHONY: up down test reset bench model defend undefend

# Turn SafeEnvelope on/off for the running challenge (starting a challenge resets it to the
# challenge's own setting). Also clears the agent's memory and scheduled tasks.
defend undefend:
	docker compose exec -T mcp-plant python -c 'import json, urllib.request as u; r = u.Request("http://localhost:8000/reset", data=json.dumps({"defended": "$@" == "defend"}).encode(), headers={"content-type": "application/json"}); print(u.urlopen(r).read().decode())'

up:
	docker compose up -d --build

# Download the agent's model once (the only step that needs internet). OLLAMA_MODEL overrides it.
model:
	docker compose --profile setup run --rm ollama-pull

down:
	docker compose down

test:
	uv run pytest

# Benchmark models (and the guard) against the challenges; see docs/BENCHMARK.md.
# e.g. make bench ARGS="--models ollama/qwen2.5:7b-instruct --runs 5 --guard on"
bench:
	uv run dvap bench $(or $(ARGS),--models fake:comply,fake:refuse --runs 1 --guard off)

# `make reset` wipes the lab's state (tickets, history, agent memory) and rebuilds. It keeps the
# downloaded model: `down -v` would delete every volume, including the 4.7 GB `ollama-models`.
# The list below is an explicit allowlist, so a reset never removes a volume it doesn't know.
# `make reset CH=C01` resets only the lab state for one challenge, in place and fast,
# by asking the scoreboard (which resets every service and clears the bus).
LAB_STATE_VOLUMES = historian-data cmms-data memory-data
reset:
ifndef CH
	docker compose down
	@project=$$(docker compose config | sed -n 's/^name: //p'); \
	for v in $(LAB_STATE_VOLUMES); do docker volume rm -f "$${project}_$$v"; done
	docker compose up -d --build
else
	curl -fsS -X POST http://127.0.0.1:8090/api/challenges/$(CH)/reset && echo " reset $(CH)"
endif

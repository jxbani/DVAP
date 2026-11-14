.PHONY: up down test reset

up:
	docker compose up -d --build

down:
	docker compose down

test:
	uv run pytest

# `make reset` wipes the whole lab (volumes included) and rebuilds.
# `make reset CH=C01` resets only the lab state for one challenge, in place and fast,
# by asking the scoreboard (which resets every service and clears the bus).
reset:
ifndef CH
	docker compose down -v
	docker compose up -d --build
else
	curl -fsS -X POST http://127.0.0.1:8090/api/challenges/$(CH)/reset && echo " reset $(CH)"
endif

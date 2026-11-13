.PHONY: up down test reset

up:
	docker compose up -d --build

down:
	docker compose down

test:
	uv run pytest

# Throw away all lab state (volumes included) and start fresh.
reset:
	docker compose down -v
	docker compose up -d --build

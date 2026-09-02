.PHONY: dev dev-backend dev-frontend docker-dev test lint report

dev:
	bash scripts/dev.sh

dev-backend:
	ARCHITECT_ROOT=$$(pwd) python -m uvicorn architect.api_server:app --host 127.0.0.1 --port 8000

dev-frontend:
	cd frontend && npm run dev -- --host 127.0.0.1 --port 5173

docker-dev:
	docker compose up --build

test:
	python -m pytest

lint:
	ruff check architect tests
	mypy architect
	cd frontend && npm run lint && npm run build

report:
	architect report . --format html --output architect-report.html

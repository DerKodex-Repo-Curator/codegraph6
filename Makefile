.PHONY: help up down build logs test test-unit test-integration index shell clean

# Default target
help:
	@echo "Oopsly Multi-Agent System"
	@echo ""
	@echo "Usage:"
	@echo "  make up          Start all services"
	@echo "  make down        Stop all services"
	@echo "  make build       Rebuild all images"
	@echo "  make logs        Tail logs from all services"
	@echo "  make test        Run unit tests"
	@echo "  make test-unit   Run unit tests only (no external deps)"
	@echo "  make index       Trigger FastAPI repo indexing"
	@echo "  make shell SVC=  Open a shell in a service container"
	@echo "  make clean       Remove all volumes and images"

up:
	docker compose up -d
	@echo "Services starting... Gateway will be at http://localhost:8080"
	@echo "Docs: http://localhost:8080/docs"

down:
	docker compose down

build:
	docker compose build --parallel

logs:
	docker compose logs -f

test:
	PYTHONPATH=. pytest tests/unit/ -v

test-unit:
	PYTHONPATH=. pytest tests/unit/ -v --tb=short

test-integration:
	PYTHONPATH=. pytest tests/integration/ -v -m integration

test-e2e:
	PYTHONPATH=. pytest tests/integration/test_orchestrator.py -v -m e2e

index:
	curl -s -X POST http://localhost:8080/api/index \
		-H "Content-Type: application/json" \
		-d '{"repository_url": "https://github.com/tiangolo/fastapi"}' | python -m json.tool

chat:
	@read -p "Question: " q; \
	curl -s -X POST http://localhost:8080/api/chat \
		-H "Content-Type: application/json" \
		-d "{\"message\": \"$$q\"}" | python -m json.tool

shell:
	docker compose exec $(SVC) /bin/bash

neo4j-browser:
	open http://localhost:7474

clean:
	docker compose down -v --rmi local
	@echo "Cleaned up containers, volumes, and local images"

.PHONY: help install up down migrate upgrade reset dev test

help:
	@echo "Comandos disponibles:"
	@echo "  make install    - Instala dependencias Python"
	@echo "  make up         - Levanta PostgreSQL y Redis con Docker"
	@echo "  make down       - Detiene los contenedores"
	@echo "  make migrate    - Genera nueva migración (uso: make migrate m='descripcion')"
	@echo "  make upgrade    - Aplica migraciones pendientes"
	@echo "  make reset      - Borra y recrea la BD (solo desarrollo)"
	@echo "  make dev        - Levanta el servidor de desarrollo"
	@echo "  make test       - Corre los tests"

install:
	pip install -r requirements.txt

up:
	docker compose up -d
	@echo "Esperando que PostgreSQL esté listo..."
	@sleep 3
	@echo "Servicios listos"

down:
	docker compose down

migrate:
	alembic revision --autogenerate -m "$(m)"

upgrade:
	alembic upgrade head

reset:
	@echo "Esto borrará toda la BD. Ctrl+C para cancelar..."
	@sleep 3
	alembic downgrade base
	alembic upgrade head

dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

test:
	pytest tests/ -v

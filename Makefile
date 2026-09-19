.PHONY: help install data demo test plan dev build serve docker

help:
	@echo "install  — поставить зависимости (python + node)"
	@echo "data     — пересобрать сценарии из выгрузки (нужна сеть для геокодинга)"
	@echo "demo     — пересобрать демонстрационный набор"
	@echo "test     — прогнать тесты"
	@echo "plan     — посчитать план в консоли и сравнить с базовым вариантом"
	@echo "dev      — запустить бэкенд и фронтенд в режиме разработки"
	@echo "build    — собрать интерфейс"
	@echo "serve    — запустить сервис на http://127.0.0.1:8000"
	@echo "docker   — собрать и запустить контейнер"

PY = .venv/Scripts/python.exe

install:
	python -m venv .venv
	$(PY) -m pip install -e .[dev]
	cd frontend && npm install

data:
	$(PY) -m planner.cli build
	$(PY) -m planner.cli geocode
	$(PY) -m planner.cli engineers

demo:
	$(PY) -m planner.cli demo

test:
	$(PY) -m pytest -q

plan:
	$(PY) -m planner.cli plan --region demo --time-limit 20

build:
	cd frontend && npm run build

serve: build
	$(PY) -m planner.cli serve

dev:
	@echo "в одном окне: $(PY) -m planner.cli serve --reload"
	@echo "в другом:     cd frontend && npm run dev"

docker:
	docker compose up --build

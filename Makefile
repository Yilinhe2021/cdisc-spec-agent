.PHONY: install examples test eval dev-api dev-web build-web run

install:
	pip install -e "backend[anthropic,openai,dev]"
	cd frontend && npm install

examples:
	python examples/make_examples.py

test:
	cd backend && pytest -q

eval:
	python eval/run_eval.py --llm $${SPECFORGE_LLM:-mock}

dev-api:
	uvicorn specforge.api.app:app --app-dir backend --reload --port 8000

dev-web:
	cd frontend && npm run dev

build-web:
	cd frontend && npm run build

run: build-web
	uvicorn specforge.api.app:app --app-dir backend --port 8000

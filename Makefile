.PHONY: install playground test run-backend run-frontend

install:
	uv pip install -e .

playground:
	agents-cli playground

test:
	uv run pytest tests/

run-backend:
	uv run uvicorn app.fast_api_app:app --host 127.0.0.1 --port 8000 --reload

run-frontend:
	cd frontend && npm install && npm run dev

generate-traces:
	.venv/Scripts/python.exe tests/eval/generate_traces.py

grade:
	.venv/Scripts/python.exe tests/eval/grade_traces.py

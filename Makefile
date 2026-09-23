.PHONY: setup smoke bench lint test build clean

setup:
	python -m pip install -e ".[all]"
	python corpus/fetch.py --sample-only

smoke:
	python -m pytest tests/ -x -q --tb=short
	tt detect corpus/sample/silence_hallucination.json --format table

bench:
	tt-bench --corpus-dir corpus/data --out eval/results/
	@echo "--- Results written to eval/results/ ---"
	@cat eval/results/summary.csv

lint:
	ruff check src/ tests/
	mypy src/

test:
	python -m pytest tests/ -v --tb=long

build:
	rm -rf dist/
	python -m build

clean:
	rm -rf corpus/data/ eval/results/*.csv dist/ build/
	find . -type d -name __pycache__ -exec rm -rf {} +

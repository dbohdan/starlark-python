.PHONY: test lint typecheck fmt zipapp clean

test:
	uv run pytest -q

lint:
	uv run ruff check src tests

typecheck:
	uv run pyright

fmt:
	uv run ruff format src tests

# Build a self-contained zipapp at ./starlark-python.pyz.
# Usage: ./starlark-python.pyz -c '1 + 2 * 3'
zipapp:
	rm -rf build/zipapp build/starlark-python.pyz
	mkdir -p build/zipapp
	cp -r src/starlark build/zipapp/
	printf 'import sys\nfrom starlark.cmd import main\nsys.exit(main())\n' > build/zipapp/__main__.py
	uv run python -m zipapp build/zipapp -o starlark-python.pyz -p '/usr/bin/env python3'
	@echo "Built ./starlark-python.pyz"
	@du -h starlark-python.pyz

clean:
	rm -rf build dist starlark-python.pyz starlark.pyz
	find . -type d -name __pycache__ -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache

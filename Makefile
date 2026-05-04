.PHONY: test lint fmt zipapp clean

test:
	uv run pytest -q

lint:
	uv run ruff check src tests

fmt:
	uv run ruff format src tests

# Build a self-contained zipapp at ./starlark.pyz.
# Usage: ./starlark.pyz -c '1 + 2 * 3'
zipapp:
	rm -rf build/zipapp build/starlark.pyz
	mkdir -p build/zipapp
	cp -r src/starlark build/zipapp/
	printf 'import sys\nfrom starlark.cmd import main\nsys.exit(main())\n' > build/zipapp/__main__.py
	uv run python -m zipapp build/zipapp -o starlark.pyz -p '/usr/bin/env python3'
	@echo "Built ./starlark.pyz"
	@du -h starlark.pyz

clean:
	rm -rf build dist starlark.pyz
	find . -type d -name __pycache__ -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache

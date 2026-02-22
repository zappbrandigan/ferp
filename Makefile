.PHONY: dev test test-cov test-host test-scripts clean bump-patch bump-minor bump-major

dev:
	FERP_DEV_CONFIG=1 FERP_SCRIPT_LOG_LEVEL=debug textual run --dev ferp/app.py

test:
	pytest -v

test-cov:
	pytest --cov=ferp --cov-report=term-missing --ignore=tests/scripts --ignore="*/__main__.py"

test-host:
	pytest -v --ignore=tests/scripts

test-scripts:
	pytest tests/scripts -v

clean:
	find . -name "__pycache__" -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache build dist *.egg-info

bump-patch:
	python scripts/bump_version.py patch

bump-minor:
	python scripts/bump_version.py minor

bump-major:
	python scripts/bump_version.py major

.PHONY: dev test clean bump-patch bump-minor bump-major

dev:
	FERP_DEV_CONFIG=1 python -m ferp

test:
	pytest

clean:
	find . -name "__pycache__" -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache build dist *.egg-info

bump-patch:
	python scripts/bump_version.py patch

bump-minor:
	python scripts/bump_version.py minor

bump-major:
	python scripts/bump_version.py major

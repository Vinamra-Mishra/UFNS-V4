# UFNS task runner. Deterministic demo path requires no secrets or network.

.PHONY: help install test demo-data dashboard lint clean

help:
	@echo "UFNS targets:"
	@echo "  install     - install runtime dependencies"
	@echo "  install-spikes - install M2/M3 spike dependencies (landlab, pyswmm)"
	@echo "  demo-data   - build data/demo bundle (synthetic fixtures + manifest)"
	@echo "  test        - run the test suite"
	@echo "  dashboard   - launch the M6 dashboard/API (http://127.0.0.1:8000)"
	@echo "  clean       - remove generated demo data"

install:
	python3 -m pip install -r requirements.txt

install-spikes:
	python3 -m pip install -r requirements-spikes.txt

demo-data:
	python3 scripts/build_demo_data.py

test:
	python3 -m pytest tests/ -v

dashboard:
	python3 scripts/run_dashboard.py

clean:
	rm -rf data/demo
	rm -rf .pytest_cache

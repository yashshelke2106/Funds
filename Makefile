PY ?= python

.PHONY: setup all offline test universe nav quality checklist report

setup:
	$(PY) -m pip install -r requirements.txt

all:
	$(PY) run_pipeline.py

offline:
	$(PY) run_pipeline.py --offline

test:
	$(PY) -m pytest -q

universe nav quality checklist report:
	$(PY) run_pipeline.py $@

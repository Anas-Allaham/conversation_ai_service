.PHONY: install install-dev test validate run demo compile

install:
	python -m pip install -e ".[agent,api,assessment]"

install-dev:
	python -m pip install -e ".[agent,api,assessment,modal,dev]"

test:
	python -m pytest

validate:
	python tools/validate_item_bank.py
	python tools/validate_scenarios.py

compile:
	python -m compileall -q src app services tools

run:
	uvicorn services.oral_assessment.main:app --host 0.0.0.0 --port 8080 --reload

demo:
	python tools/api_smoke_test.py

.PHONY: install install-dev test validate run demo compile

install:
	python -m pip install -e ".[livekit]"

install-dev:
	python -m pip install -e ".[livekit,dev]"

test:
	python -m unittest discover -s services/oral_assessment/tests -t . -v

validate:
	python tools/validate_item_bank.py
	python tools/validate_scenarios.py

compile:
	python -m compileall -q app services tools

run:
	uvicorn services.oral_assessment.main:app --host 0.0.0.0 --port 8080 --reload

demo:
	python tools/api_smoke_test.py

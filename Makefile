.PHONY: help ci ci-live doctor golden lint test model

# Use the venv explicitly so `make ci` works without activating it first — and so CI and a
# developer shell run the same interpreter.
PY := ./venv/bin/python
BIN := ./venv/bin

help:
	@echo "make ci        — lint + contracts + unit/property/golden/contract/perf. No hardware, no network."
	@echo "make ci-live   — re-run every Jev point against the live API, diff vs fixtures/judgment/"
	@echo "make doctor    — check this machine: camera, uinput, AT-SPI, mediapipe, Jev key"
	@echo "make golden    — regenerate golden intent streams (review the diff!)"
	@echo "make lint      — import contracts + magic-number check"

lint:
	$(BIN)/lint-imports
	$(PY) tools/check_no_magic_numbers.py

test:
	$(PY) -m pytest tests/unit tests/property tests/golden tests/contract tests/perf -q

ci: lint test

ci-live:
	$(PY) -m pytest tests/live -q -m live

doctor:
	$(PY) main.py doctor

golden:
	$(PY) main.py golden --update

model:
	@mkdir -p models
	@test -f models/hand_landmarker.task || curl -fsSL -o models/hand_landmarker.task \
		https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task
	@echo "models/hand_landmarker.task ready"

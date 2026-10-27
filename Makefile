PYTHON ?= .venv/bin/python

.PHONY: test test-fast

# Full suite: every test, slow end-to-end suites included.
test:
	$(PYTHON) -m pytest -q

# Fast lane: opt-in only, deselects the heavy end-to-end suites.
test-fast:
	$(PYTHON) -m pytest -q -m "not slow"

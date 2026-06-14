# Hermes Loom — common dev/ops tasks.
# Override Python or the serve host/port from the command line, e.g.:
#   make serve PORT=9000
#   make sync PY=python3.12

PY   ?= python3
HOST ?= 127.0.0.1
PORT ?= 8765

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

## --- daily ops -------------------------------------------------------------

.PHONY: sync
sync: ## Import current memory+skills, then backfill events from state.db
	$(PY) -m hermes_loom sync

.PHONY: serve
serve: ## Run the local API + UI on 127.0.0.1 (HOST/PORT overridable)
	$(PY) -m hermes_loom serve --host $(HOST) --port $(PORT)

.PHONY: serve-lan
serve-lan: ## Run on 0.0.0.0 for LAN access — WARNING: no auth, exposes write endpoints
	@printf '\033[33m⚠  Binding 0.0.0.0:%s — Loom has no auth and can edit Hermes memory/skills.\n   Only do this on a trusted network.\033[0m\n' '$(PORT)'
	$(PY) -m hermes_loom serve --host 0.0.0.0 --port $(PORT)

.PHONY: status
status: ## Print ledger event counts by kind
	$(PY) -m hermes_loom status

.PHONY: bootstrap
bootstrap: ## Import current memory+skills as historical snapshots
	$(PY) -m hermes_loom bootstrap

.PHONY: ingest
ingest: ## Backfill precise growth events from state.db tool calls
	$(PY) -m hermes_loom ingest

.PHONY: reconcile
reconcile: ## Run the snapshot-diff fallback now
	$(PY) -m hermes_loom reconcile

## --- quality ---------------------------------------------------------------

.PHONY: test
test: ## Run the Python unittest suite
	$(PY) -m unittest discover -s tests -p 'test_*.py' -v

.PHONY: test-ui
test-ui: ## Run the JS component test (Inspector skill filter, needs node)
	node tests/ui_filter_test.js

.PHONY: compile
compile: ## Byte-compile sources + syntax-check the UI
	$(PY) -m py_compile hermes_loom/*.py tests/*.py && echo "compile OK"
	node --check hermes_loom/ui/app.js && echo "app.js syntax OK"

.PHONY: check
check: compile test test-ui ## compile + python tests + UI component test

## --- packaging -------------------------------------------------------------

.PHONY: build
build: ## Build the wheel + sdist into dist/ (uv if present, else python -m build)
	@command -v uv >/dev/null 2>&1 && uv build || $(PY) -m build
	@echo "built dist/ — pip install dist/*.whl"

.PHONY: install
install: ## pip-install Loom into the current environment (service + Hermes plugin)
	$(PY) -m pip install .

.PHONY: install-plugin
install-plugin: ## Copy the plugin into a Hermes install ($HERMES_HOME/plugins) — local or SSH host: make install-plugin HOST=rpi
	./scripts/install-plugin.sh $(HOST)

## --- housekeeping ----------------------------------------------------------

.PHONY: clean
clean: ## Remove caches and build artifacts (never touches the ledger)
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf build dist *.egg-info .pytest_cache
	@echo "cleaned"

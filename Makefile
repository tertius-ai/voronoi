NOETHER_ROOT := $(abspath ../noether)
FLINT_PREFIX ?= $(shell cat $(NOETHER_ROOT)/.deps/flint/prefix.txt 2>/dev/null || echo $(NOETHER_ROOT)/.deps/flint)
export FLINT_PREFIX
export PKG_CONFIG_PATH := $(FLINT_PREFIX)/lib/pkgconfig:$(PKG_CONFIG_PATH)
export LD_LIBRARY_PATH := $(FLINT_PREFIX)/lib:$(LD_LIBRARY_PATH)
export DYLD_LIBRARY_PATH := $(FLINT_PREFIX)/lib:$(DYLD_LIBRARY_PATH)

.PHONY: sync engine doctor test test-fast test-rust test-python test-corpus check-data lint

sync:
	uv sync --locked
	PY="$(CURDIR)/.venv/bin/python" "$(NOETHER_ROOT)/scripts/install-native-deps.sh"
	.venv/bin/python "$(NOETHER_ROOT)/scripts/gen_py_api_doc.py"

engine:
	cargo build --locked --release -p voronoi-census-engine

doctor:
	.venv/bin/voronoi doctor

test: test-rust test-python

test-rust: engine
	cargo test --locked --release -p voronoi-census-engine

test-python: engine
	.venv/bin/python -m pytest -q

test-fast: engine
	.venv/bin/python -m pytest -q -m 'not corpus'

check-data:
	PYTHON="$(CURDIR)/.venv/bin/python" scripts/fetch_database.sh --check

test-corpus: engine check-data
	VORONOI_RUN_CENSUS_REGRESSION=1 .venv/bin/python -m pytest -q

lint:
	.venv/bin/ruff check src tests scripts
	cargo fmt --all -- --check
	@for script in scripts/*.sh; do bash -n "$$script"; done

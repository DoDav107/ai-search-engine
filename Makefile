# Single launcher for the SEO/GEO audit tool. Config-driven and client-agnostic
# (the client/site comes from config/*.yaml — nothing is hardcoded here).
#
#   make pipeline    run the full audit (writes latest_report.json + history + PDF)
#   make dashboard   launch the Streamlit dashboard
#   make web         launch the Next.js dashboard
#   make all         launch BOTH dashboards together (Ctrl-C stops both)

# Use the project venv's python if present, otherwise fall back to system python3.
PYTHON := $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)
WEB_DIR := web-dashboard
STREAMLIT_PORT ?= 8501
WEB_PORT ?= 3000

.DEFAULT_GOAL := help

.PHONY: help install pipeline dashboard web all check-ports

help:  ## Show available targets
	@echo "Usage: make <target>"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:  ## Install Python + Node deps and the Playwright (PDF) browser
	$(PYTHON) -m pip install -r requirements.txt
	$(PYTHON) -m playwright install chromium
	cd $(WEB_DIR) && npm install

pipeline:  ## Run the full audit pipeline (latest_report.json + history copy + PDF)
	$(PYTHON) -m src.pipeline

dashboard:  ## Launch the Streamlit dashboard (http://localhost:$(STREAMLIT_PORT))
	$(PYTHON) -m streamlit run src/dashboard/app.py --server.port $(STREAMLIT_PORT)

web:  ## Launch the Next.js dashboard (http://localhost:$(WEB_PORT))
	cd $(WEB_DIR) && npm run dev -- -p $(WEB_PORT)

check-ports:
	@for port in $(STREAMLIT_PORT) $(WEB_PORT); do \
		if lsof -n -P -iTCP:$$port -sTCP:LISTEN >/dev/null 2>&1; then \
			echo "Port $$port is already in use:"; \
			lsof -n -P -iTCP:$$port -sTCP:LISTEN; \
			echo ""; \
			echo "Stop that process first, or run with a different port, e.g. WEB_PORT=3001 make all"; \
			exit 1; \
		fi; \
	done

all: check-ports  ## Launch BOTH dashboards together; Ctrl-C stops both
	@echo "Streamlit -> http://localhost:$(STREAMLIT_PORT)   Next.js -> http://localhost:$(WEB_PORT)"
	@echo "(Ctrl-C stops both)"
	@cleanup() { \
		trap - INT TERM EXIT; \
		[ -n "$$streamlit_pid" ] && kill "$$streamlit_pid" >/dev/null 2>&1 || true; \
		[ -n "$$web_pid" ] && kill "$$web_pid" >/dev/null 2>&1 || true; \
	}; \
	trap 'cleanup; exit 0' INT TERM; \
	trap cleanup EXIT; \
	$(PYTHON) -m streamlit run src/dashboard/app.py --server.port $(STREAMLIT_PORT) --server.headless true & \
	streamlit_pid=$$!; \
	( cd $(WEB_DIR) && npm run dev -- -p $(WEB_PORT) ) & \
	web_pid=$$!; \
	while kill -0 "$$streamlit_pid" >/dev/null 2>&1 && kill -0 "$$web_pid" >/dev/null 2>&1; do \
		sleep 1; \
	done; \
	wait "$$streamlit_pid" >/dev/null 2>&1; streamlit_status=$$?; \
	wait "$$web_pid" >/dev/null 2>&1; web_status=$$?; \
	if [ "$$streamlit_status" -ne 0 ] && [ "$$streamlit_status" -ne 143 ]; then exit "$$streamlit_status"; fi; \
	if [ "$$web_status" -ne 0 ] && [ "$$web_status" -ne 143 ]; then exit "$$web_status"; fi

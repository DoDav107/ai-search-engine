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

.PHONY: help install pipeline dashboard web all

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

all:  ## Launch BOTH dashboards together; Ctrl-C stops both
	@echo "Streamlit -> http://localhost:$(STREAMLIT_PORT)   Next.js -> http://localhost:$(WEB_PORT)"
	@echo "(Ctrl-C stops both)"
	@trap 'kill 0' INT TERM EXIT; \
	$(PYTHON) -m streamlit run src/dashboard/app.py --server.port $(STREAMLIT_PORT) --server.headless true & \
	( cd $(WEB_DIR) && npm run dev -- -p $(WEB_PORT) ) & \
	wait

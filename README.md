# AI-Driven Search Ranking & Optimisation Engine

A minimal scaffold for an SEO + GEO diagnostic tool with a Python data engine, future AI agents, and a Streamlit dashboard.

## Project Layers

1. **Data engine**: crawler, SEO factor extraction, scoring
2. **AI agents**: GEO research, content drafting (future)
3. **Dashboard**: Streamlit analytics UI (future)

## What is included

- `config/` for crawl rules and scoring weights
- `src/engine/` for crawler, extractors, scoring, and models
- `src/agents/` stubbed future agent layer
- `src/dashboard/` stubbed future dashboard app
- `data/raw/` and `data/reports/` for persisted assets
- `tests/` for future unit tests
- `docs/SPEC.md` for architecture and scope

## Getting started

1. Create a Python virtual environment.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and populate API keys when ready.

## Notes

This repository is currently a skeleton. The first implementation phase focuses on the data engine only. Agents and dashboard layers are intentionally stubbed for later development.

# AI-Driven Search Ranking & Optimisation Engine Specification

## Architecture

The project is structured in three sequential layers:

1. **Data Engine** (implemented first)
   - Web crawler
   - SEO factor extractors
   - Page and site scoring logic
2. **AI Agents** (future)
   - `geo_agent`: GEO research for regional search insights
   - `drafting_agent`: SEO-aware content drafting
3. **Dashboard** (future)
   - Streamlit UI for reports and optimisation guidance

## Week 1 Scope

- Create the repository scaffold and config files.
- Define the data engine contract with stubs only.
- Provide YAML config for crawl settings and factor weights.
- Add the first unit-test placeholder.

## SEO Factors

The engine evaluates these seven factors for each crawled page:

- `title`
- `meta_description`
- `h1`
- `canonical`
- `image_alt`
- `word_count`
- `structured_data`

Each factor returns a `FactorResult` with:

- `id`: factor name
- `status`: one of `pass`, `warn`, `fail`
- `value`: raw extracted value or metric
- `message`: human-readable note

## Scoring Approach

- `score_page(factors)` computes a normalized page score between 0 and 100.
- `score_site(pages)` aggregates page scores into a site-level score.
- Factor statuses should map to values like:
  - `pass` → 1.0
  - `warn` → 0.5
  - `fail` → 0.0
- The final score is weighted by `config/scoring_weights.yaml` and normalized.

## Approved Decisions

- Use **Google Search Console** as the initial SEO data source for later integration.
- Use a **single AI provider** behind an Eloize-owned API key.
- Reuse **permissively-licensed open-source components** for parsing, crawling, and analytics.

## Config Files

- `config/crawl_config.yaml` contains crawl rules, site metadata, and active factors.
- `config/scoring_weights.yaml` keeps factor weights separate from code so tuning can happen without logic changes.

## Future Implementation Notes

- `src/engine/crawler.py` will fetch pages politely and store raw HTML in `data/raw/`.
- `src/engine/extractors.py` will parse HTML and return factor results.
- `src/engine/scoring.py` will implement the normalized scoring algorithm.
- `src/agents/` and `src/dashboard/app.py` remain stubbed until the data engine is functional.

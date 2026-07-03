# AI-Driven SEO & GEO Audit Engine

An automated diagnostic tool that crawls a website, scores on-page SEO factors, measures brand visibility in AI-generated answers (Generative Engine Optimisation — GEO), combines both into a unified score, and produces prioritised recommendations with review-ready draft fixes. Everything is surfaced in a Streamlit dashboard. The tool is read-only: it never modifies the live site, and draft fixes are always human-approved before use.

## Architecture

Three layers, each independently runnable:

| Layer | Location | Responsibility |
|---|---|---|
| **Data engine** | `src/engine/` | Crawl, extract SEO factors, score, build recommendations |
| **AI agents** | `src/agents/` | GEO brand-visibility research; content-drafting of fixes |
| **Dashboard** | `src/dashboard/` | Read-only Streamlit UI over saved JSON reports |

---

## 1. Setup

**Python 3.13+ required.**

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**API key (optional for live GEO/drafting):**

```bash
cp .env.example .env
# Edit .env and fill in ANTHROPIC_API_KEY or OPENAI_API_KEY
```

The key is only needed if you switch `engine` in `config/geo_config.yaml` from `"mock"` to `"anthropic"` or `"openai"`. All other functionality — crawling, SEO scoring, recommendations, dashboard — runs without it. The `.env` file is gitignored; never commit it.

**Saving keys from the dashboard (`ALLOW_ENV_KEY_WRITE`, default off):** The New Audit form
can optionally write a provider key into the server `.env` ("Save this key to the server
for future audits"). This is **disabled by default** and only appears/works when
`ALLOW_ENV_KEY_WRITE=true` is set in the server `.env`. It is intended for **local/trusted,
single-user use only** — it persists a secret to disk. **Keep it disabled on any public or
multi-user/hosted deployment.** The write happens server-side only (`src/reporting/env_key.py`);
the key is sent over a dedicated route on stdin and is never echoed back to the browser,
never logged, and never stored in reports or per-job configs. A server/pipeline restart may
be needed for a freshly saved key to take effect.

---

## 2. Usage

Run everything from the **repo root** with the venv active. Steps can be run individually or all at once via the pipeline.

### One-command launcher (Makefile)

A single entry point runs the pipeline and both dashboards. Targets are config-driven and client-agnostic (the site/brand comes from `config/*.yaml`):

```bash
make pipeline     # run the full audit → data/reports/latest_report.json + history + PDF
make dashboard    # launch the Streamlit dashboard   (http://localhost:8501)
make web          # launch the Next.js dashboard     (http://localhost:3000)
make all          # launch BOTH dashboards together  (Ctrl-C stops both)
make install      # install Python + Node deps and the Playwright (PDF) browser
make help         # list all targets
```

Ports are overridable, e.g. `make all STREAMLIT_PORT=8600 WEB_PORT=3100`. The launcher uses `.venv/bin/python` automatically if a venv is present.

### Report history

Every pipeline run keeps `data/reports/latest_report.json` as the "most recent" pointer **and** writes an immutable, timestamped copy under `data/reports/history/<client>/<YYYY-MM-DDTHH-MM-SSZ>.json`, so past runs are never overwritten (this is what a future trend view reads). List a client's history programmatically:

```python
from src.reporting.history import list_reports, list_clients
list_clients()             # e.g. ["nike"]
list_reports("Nike")       # paths sorted oldest → newest
```

### Full pipeline (recommended)

Crawls the site, scores SEO factors, runs GEO queries, combines scores, and saves a unified report to `data/reports/`:

```bash
python -m src.pipeline
```

Then generate prioritised recommendations and draft fixes:

```bash
python -m src.engine.recommendations
python -m src.agents.drafting_agent
```

Launch the dashboard to visualise everything:

```bash
streamlit run src/dashboard/app.py
```

### Running each stage individually

```bash
# 1. Crawl pages and cache HTML to data/raw/
python -m src.engine.crawler

# 2. Extract SEO factors and score pages
python -m src.engine.scoring

# 3. Run GEO brand-visibility queries
python -m src.agents.geo_agent

# 4. Build prioritised recommendations from the latest site report
python -m src.engine.recommendations

# 5. Generate review-ready draft fixes for each recommendation
python -m src.agents.drafting_agent
```

Recommendations and draft fixes are printed to stdout and saved to `data/reports/` as timestamped JSON files. The dashboard automatically picks up the most recent file of each type.

---

## 3. Configuration

All config lives in `config/`. Edit these files to point the tool at a different site, tune scoring, or switch to a live AI engine.

### `config/crawl_config.yaml`

Controls the crawler and which SEO factors are checked.

```yaml
site:
  name: "Eloize / RemindX"
  base_url: "https://www.eloize.io"
  seed_urls: ["/"]            # Starting paths (resolved against base_url)

crawl:
  max_pages: 15               # Hard cap on pages fetched per run
  max_depth: 1                # Link depth from seed URLs
  delay_seconds: 1.0          # Polite pause between requests
  user_agent: "EloizeSEOBot/0.1"
  respect_robots_txt: true    # Honour robots.txt disallow rules
  timeout_seconds: 10         # Per-request HTTP timeout

factors:                      # SEO factors to extract and score
  - title
  - meta_description
  - h1
  - canonical
  - image_alt
  - word_count
  - structured_data
```

### `config/scoring_weights.yaml`

Multiplier applied to each factor's pass/warn/fail score when computing the weighted page score. Default is 1.0 (equal weight). Increase a value to make that factor count more toward the overall SEO score.

```yaml
title: 1.0
meta_description: 1.0
h1: 1.0
canonical: 1.0
image_alt: 1.0
word_count: 1.0
structured_data: 1.0
```

### `config/geo_config.yaml`

Controls the GEO agent: which AI engine to query, the brand to track, any competitors to detect, and the set of queries to run.

```yaml
engine: "mock"          # "mock" | "anthropic" | "openai"
brand: "Eloize"
competitors: []
queries:
  - "How can I automate repetitive tasks in my startup?"
  - "What AI tools help small business founders manage growth?"
  # ... (8 queries total)
```

`engine: "mock"` returns deterministic canned answers and requires no API key — the default for development. Set `engine: "anthropic"` or `engine: "openai"` and add the corresponding key to `.env` to run against a live model.

### `config/pipeline_config.yaml`

Weights used when combining the SEO and GEO scores into a single unified score. Values are normalised, so only their ratio matters.

```yaml
seo_weight: 0.5
geo_weight: 0.5
```

### Keeping AI models up to date

**Where the list lives:** `config/models.yaml`. This one file is the single source of truth for the "AI model" dropdown on **both** the Streamlit dashboard and the Next.js web form — edit it once and both surfaces update.

**How to add or update a model (the common case) — a one-line edit, no code change, no redeploy.** Under `providers:`, each provider has a `models:` list. Every entry maps a consumer-facing `label` (what the user sees, e.g. `"GPT-5.5"`) to the provider's real `api_id` (the id actually sent to the API), plus:

- `grounding: true`/`false` — whether the model answers with live web search, which GEO relies on. Models with `grounding: false` are shown in the dropdown marked `(no GEO grounding)`.
- `default: true` — optional; marks the flagship that is pre-selected for that provider (one per provider).

```yaml
providers:
  openai:
    models:
      - { label: "GPT-5.5", api_id: "gpt-5.5", grounding: true, default: true }
      - { label: "GPT-4o",  api_id: "gpt-4o",  grounding: true }
```

**Worked example — a provider retires a model and ships a new one (GPT-5.5 → GPT-6):** open `config/models.yaml`, find the `openai:` section, add the new line and drop (or keep) the old one, then save. Done — no restart or code change needed.

```yaml
  openai:
    models:
      - { label: "GPT-6",   api_id: "gpt-6",   grounding: true, default: true }   # new flagship
      # - { label: "GPT-5.5", api_id: "gpt-5.5", grounding: true }                # old line, removed
```

**How you'll know a model is retired:** if an audit is run with an `api_id` the provider no longer accepts, the tool fails with a clear message — *"…rejected the model id '…' — it may be retired or renamed. Update config/models.yaml with the current api_id for this model."* — instead of a silent 0%. A failing model is self-explaining: just update its `api_id` in this file.

**All providers use the same file.** OpenAI, Gemini (`google:`), Anthropic, xAI, Perplexity, etc. are each just another section under `providers:`, updated the same one-line way.

**⚠️ Adding a model vs. adding a provider — not the same job:**

- **Add or update a MODEL for a provider that's already wired in** → a one-line edit to `config/models.yaml`. That's it.
- **Add a brand-new PROVIDER that isn't wired in yet** → *not* just a config edit. It first requires building that provider's API client/integration **in code**, and only then listing its models here. Config alone will not make a new provider work.

---

## 4. Project Structure

```
.
├── config/
│   ├── crawl_config.yaml       # Site, crawl limits, factor list
│   ├── scoring_weights.yaml    # Per-factor scoring weights
│   ├── geo_config.yaml         # GEO engine, brand, queries
│   └── pipeline_config.yaml    # SEO/GEO blend weights
│
├── src/
│   ├── pipeline.py             # Orchestrates full SEO+GEO run; saves combined report
│   │
│   ├── engine/
│   │   ├── crawler.py          # HTTP crawler with robots.txt support, HTML caching
│   │   ├── extractors.py       # Per-factor SEO signal extraction from raw HTML
│   │   ├── scoring.py          # Weighted page and site score aggregation
│   │   ├── recommendations.py  # Builds prioritised Recommendation list from site report
│   │   └── models.py           # Dataclasses: FactorResult, PageReport, SiteReport,
│   │                           #   GeoReport, CombinedReport, Recommendation, DraftedFix
│   │
│   ├── agents/
│   │   ├── geo_agent.py        # GEO queries; EngineClient ABC + MockEngineClient
│   │   └── drafting_agent.py   # Drafts review-ready fixes per recommendation
│   │
│   └── dashboard/
│       └── app.py              # Streamlit dashboard (read-only, no crawling or API calls)
│
├── data/
│   ├── raw/                    # Cached HTML pages from the last crawl run
│   └── reports/                # Timestamped JSON reports (site, combined, recommendations)
│
├── docs/
│   └── SPEC.md                 # Architecture and scope specification
│
├── tests/
│   └── test_extractors.py      # Unit tests for SEO factor extractors
│
├── requirements.txt
├── .env.example
└── README.md
```

---

## 5. Notes & Scope

**This is a diagnostic tool.** It reads a live site and produces a report. It never writes to, deploys to, or otherwise modifies the target website. Draft fixes generated by `drafting_agent` are suggestions only — they carry a `status: "pending_review"` flag and must be reviewed and applied manually.

**Scoring is deliberately simple and tunable.** SEO factors are scored pass / warn / fail with configurable per-factor weights. GEO score is derived from brand mention prominence across the configured queries. Both are intended as directional signals, not authoritative benchmarks — adjust `scoring_weights.yaml` and `pipeline_config.yaml` to reflect your priorities.

**GEO and drafting agents currently run against a mock engine.** The `MockEngineClient` returns deterministic canned answers so the full pipeline — including recommendations and draft fixes — works without an API key. Switching to a live model is a one-line config change (`engine: "anthropic"`) once a key is available.

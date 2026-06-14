"""Content-drafting agent: produces review-ready draft fixes for SEO recommendations."""

from __future__ import annotations

from typing import Any

from .geo_agent import EngineClient, MockEngineClient, get_engine_client
from ..engine.models import DraftedFix, Recommendation


# ---------------------------------------------------------------------------
# Mock client with canned drafts for each SEO factor
# ---------------------------------------------------------------------------

class DraftingMockEngineClient(MockEngineClient):
    """MockEngineClient extended with canned drafting responses per SEO factor."""

    _DRAFTS: dict[str, str] = {
        "title": "Eloize: AI Workflow Automation for Founder-Led Teams",
        "meta_description": (
            "Eloize helps founder-led SMBs automate repetitive workflows, "
            "govern AI systems, and scale operations — try it free today."
        ),
        "h1": "Automate Your Business Workflows with Eloize",
        "canonical": (
            "Add to the <head> of each page:\n"
            '<link rel="canonical" href="https://eloize.com/your-page-path/">'
        ),
        "image_alt": (
            "Example alt texts:\n"
            '- alt="Eloize dashboard showing active workflow automations"\n'
            '- alt="Founder reviewing AI-generated business report on laptop"\n'
            '- alt="Eloize onboarding screen with workflow templates"'
        ),
        "word_count": (
            "Suggested content sections to reach 300+ words:\n"
            "1. The problem — manual, repetitive operations slow growth\n"
            "2. How Eloize solves it — AI-powered, no-code automations\n"
            "3. Key features — workflow builder, AI governance, analytics\n"
            "4. Customer story — 2-sentence proof point from a real founder\n"
            "5. Call to action — start free, no credit card required"
        ),
        "structured_data": (
            "{\n"
            '  "@context": "https://schema.org",\n'
            '  "@type": "SoftwareApplication",\n'
            '  "name": "Eloize",\n'
            '  "description": "AI-powered workflow automation for founder-led SMBs",\n'
            '  "applicationCategory": "BusinessApplication",\n'
            '  "operatingSystem": "Web",\n'
            '  "offers": {\n'
            '    "@type": "Offer",\n'
            '    "price": "0",\n'
            '    "priceCurrency": "USD"\n'
            "  }\n"
            "}"
        ),
    }

    def query(self, prompt: str) -> str:
        """Return a canned draft when the prompt is a drafting request; fall back to parent."""
        for factor, draft in self._DRAFTS.items():
            if f"Factor: {factor}" in prompt:
                return draft
        return super().query(prompt)


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------

def _get_draft_client(config: dict[str, Any]) -> EngineClient:
    """Return a drafting-aware client; uses DraftingMockEngineClient for mock."""
    if config.get("engine", "mock").lower() == "mock":
        return DraftingMockEngineClient()
    return get_engine_client(config)


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

_FACTOR_TASK: dict[str, str] = {
    "title": (
        "Write a rewritten page title: 10–60 characters, descriptive, keyword-rich. "
        "Return the title text only."
    ),
    "meta_description": (
        "Write a meta description: 50–160 characters, includes a call to action. "
        "Return the description text only."
    ),
    "h1": (
        "Write a single H1 heading for the page: concise, keyword-relevant, under 70 characters. "
        "Return the heading text only."
    ),
    "canonical": (
        "Write the corrected canonical <link> tag for each affected page, "
        "using the page's own URL as the canonical href."
    ),
    "image_alt": (
        "Write example alt text for affected images: descriptive, 5–15 words each. "
        "Return one example alt attribute per image context."
    ),
    "word_count": (
        "Write a brief outline of 3–5 content sections to expand each page to at least 300 words. "
        "Include a suggested opening sentence per section."
    ),
    "structured_data": (
        "Write a complete JSON-LD structured data block appropriate for this page type, "
        "ready to paste inside a <script type='application/ld+json'> tag."
    ),
}


def build_drafting_prompt(rec: Recommendation) -> str:
    """Build a clear, factor-specific drafting prompt for the given recommendation."""
    pages = "\n".join(f"  - {url}" for url in rec.affected_urls)
    task = _FACTOR_TASK.get(
        rec.factor,
        "Describe a concrete, copy-paste-ready fix for this SEO factor.",
    )
    return (
        f"You are an SEO expert producing a review-ready draft fix.\n\n"
        f"Factor: {rec.factor}\n"
        f"Severity: {rec.severity}\n"
        f"Scope: {rec.scope}\n"
        f"Issue: {rec.message}\n"
        f"Affected pages:\n{pages}\n\n"
        f"Task: {task}\n\n"
        f"Produce a concrete, copy-paste-ready suggestion. "
        f"This draft is for human review only — it will not be applied automatically."
    )


# ---------------------------------------------------------------------------
# Main drafting function
# ---------------------------------------------------------------------------

def draft_fixes(recommendations: list[Recommendation], config: dict[str, Any]) -> list[DraftedFix]:
    """Draft a review-ready fix for each recommendation. Errors are captured gracefully."""
    client = _get_draft_client(config)
    fixes: list[DraftedFix] = []
    for rec in recommendations:
        prompt = build_drafting_prompt(rec)
        try:
            draft = client.query(prompt)
        except Exception as exc:
            draft = f"[Draft error: {exc}]"
        fixes.append(DraftedFix(recommendation=rec, draft=draft, status="pending_review"))
    return fixes


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    from ..engine.recommendations import (
        _build_site_report,
        _load_recommendation_weights,
        build_recommendations,
    )
    from .geo_agent import load_geo_config

    TOP_N = 5

    site_report = _build_site_report()
    weights = _load_recommendation_weights()
    recommendations = build_recommendations(site_report, weights)

    geo_config = load_geo_config()
    draft_config: dict[str, Any] = {"engine": geo_config.get("engine", "mock")}

    top = recommendations[:TOP_N]
    drafted = draft_fixes(top, draft_config)

    print(f"Drafted fixes for top {len(drafted)} recommendation(s)\n")
    print("=" * 60)
    for df in drafted:
        rec = df.recommendation
        print(f"\nFactor:   {rec.factor}")
        print(f"Severity: {rec.severity}  |  Scope: {rec.scope}  |  Priority: {rec.priority:.1f}")
        print(f"Pages:    {', '.join(rec.affected_urls)}")
        print(f"Issue:    {rec.message}")
        print(f"Status:   {df.status}")
        print("Draft fix:")
        for line in df.draft.splitlines():
            print(f"  {line}")
        print("-" * 60)


if __name__ == "__main__":
    main()

"""Extract SEO factor results from parsed HTML content."""

from __future__ import annotations

import re
from typing import Any

import yaml
from bs4 import BeautifulSoup

from .crawler import crawl, load_config
from .models import CrawledPage, FactorResult, PageReport


def _text_length(value: str | None) -> int:
    return len(value.strip()) if value else 0


def title(html: Any) -> FactorResult:
    """Extract the page title factor from parsed HTML."""
    title_tag = html.title
    text = title_tag.string.strip() if title_tag and title_tag.string else ""
    length = _text_length(text)
    if not text:
        status = "fail"
        message = "Title is missing; add a descriptive title between 10 and 60 characters."
    elif 10 <= length <= 60:
        status = "pass"
        message = "Title is present and within the recommended length range."
    else:
        status = "warn"
        message = f"Title length is {length}. Aim for 10–60 characters for better search visibility."
    return FactorResult(id="title", status=status, value={"text": text, "length": length}, message=message)


def meta_description(html: Any) -> FactorResult:
    """Extract the meta description factor from parsed HTML."""
    description_tag = html.find("meta", attrs={"name": "description"})
    description = description_tag.get("content", "").strip() if description_tag else ""
    length = _text_length(description)
    if not description:
        status = "fail"
        message = "Meta description is missing; add a concise summary between 50 and 160 characters."
    elif 50 <= length <= 160:
        status = "pass"
        message = "Meta description is present and within the recommended length range."
    else:
        status = "warn"
        message = f"Meta description length is {length}. Aim for 50–160 characters for improved SERP snippets."
    return FactorResult(id="meta_description", status=status, value={"text": description, "length": length}, message=message)


def h1(html: Any) -> FactorResult:
    """Extract the first H1 heading factor from parsed HTML."""
    headings = html.find_all("h1")
    count = len(headings)
    first_text = headings[0].get_text(strip=True) if headings else ""
    if count == 1:
        status = "pass"
        message = "Exactly one H1 heading was found."
    elif count == 0:
        status = "fail"
        message = "No H1 heading found; include a single, descriptive H1 on the page."
    else:
        status = "warn"
        message = f"{count} H1 headings found; use a single H1 for clearer page structure."
    return FactorResult(id="h1", status=status, value={"count": count, "first_h1": first_text}, message=message)


def canonical(html: Any) -> FactorResult:
    """Extract the canonical URL factor from parsed HTML."""
    canonical_tag = html.find("link", rel=lambda value: value and "canonical" in value if isinstance(value, str) else value and "canonical" in " ".join(value))
    canonical_url = canonical_tag.get("href", "").strip() if canonical_tag else ""
    if canonical_url:
        status = "pass"
        message = "Canonical link is present."
    else:
        status = "warn"
        message = "Canonical link is missing; add a canonical URL to avoid duplicate content issues."
    return FactorResult(id="canonical", status=status, value=canonical_url or None, message=message)


def image_alt(html: Any) -> FactorResult:
    """Extract the image alt text coverage factor from parsed HTML."""
    images = html.find_all("img")
    total = len(images)
    if total == 0:
        status = "pass"
        message = "No images present on this page, so image alt coverage is not applicable."
        return FactorResult(id="image_alt", status=status, value="0 of 0 images have alt text", message=message)

    with_alt = sum(1 for img in images if img.get("alt") and img.get("alt").strip())
    ratio = int(with_alt / total * 100)
    value = f"{with_alt} of {total} images have alt text"
    if ratio >= 90:
        status = "pass"
        message = "Most images include alt text, which is good for accessibility and SEO."
    elif ratio >= 50:
        status = "warn"
        message = f"Only {ratio}% of images have alt text; add descriptive alt text for more images."
    else:
        status = "fail"
        message = f"Only {ratio}% of images have alt text; improve ALT coverage for SEO and accessibility."
    return FactorResult(id="image_alt", status=status, value=value, message=message)


def word_count(html: Any) -> FactorResult:
    """Extract the word count factor from parsed HTML."""
    for tag in html(["script", "style"]):
        tag.extract()
    text = html.get_text(separator=" ", strip=True)
    words = re.findall(r"\w+", text)
    count = len(words)
    if count > 500:
        status = "pass"
        message = "The page has strong content volume."
    elif count >= 200:
        status = "warn"
        message = "Content volume is moderate; consider adding more helpful text."
    else:
        status = "fail"
        message = "Thin content detected; add at least 200 words of meaningful copy."
    return FactorResult(id="word_count", status=status, value=count, message=message)


def structured_data(html: Any) -> FactorResult:
    """Extract structured data factor from parsed HTML."""
    scripts = html.find_all("script", attrs={"type": "application/ld+json"})
    count = len(scripts)
    if count >= 1:
        status = "pass"
        message = "Structured data is present on the page."
    else:
        status = "warn"
        message = "No JSON-LD structured data found; add schema markup if relevant."
    return FactorResult(id="structured_data", status=status, value=count, message=message)


def _parse_html(html: str) -> Any:
    return BeautifulSoup(html, "lxml")


def extract_page(page: CrawledPage, config: dict[str, Any]) -> PageReport:
    """Create a PageReport by running configured SEO factor extractors."""
    if page.status_code != 200 or not page.html:
        return PageReport(url=page.url, factors=[], score=0.0)

    soup = _parse_html(page.html)
    factor_names = config.get("factors", [])
    factor_map = {
        "title": title,
        "meta_description": meta_description,
        "h1": h1,
        "canonical": canonical,
        "image_alt": image_alt,
        "word_count": word_count,
        "structured_data": structured_data,
    }

    factors: list[FactorResult] = []
    for name in factor_names:
        extractor = factor_map.get(name)
        if extractor:
            factors.append(extractor(soup))
    return PageReport(url=page.url, factors=factors, score=0.0)


def main() -> None:
    config = load_config()
    pages = crawl(config)
    reports = [extract_page(page, config) for page in pages]

    print(f"Processed {len(reports)} pages")
    for report, page in zip(reports, pages):
        print("\n" + "=" * 80)
        print(f"URL: {report.url}")
        if not report.factors:
            error = page.error or f"HTTP {page.status_code}" if page.status_code else "Unknown fetch issue"
            print(f"Fetch failed: {error}")
            continue
        for factor in report.factors:
            print(f"- {factor.id}: {factor.status} — {factor.message}")


if __name__ == "__main__":
    main()

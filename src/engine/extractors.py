"""Extract SEO factor results from parsed HTML content."""

from __future__ import annotations

import re
import unicodedata
from typing import Any
from urllib.parse import urlparse

import yaml
from bs4 import BeautifulSoup

from .crawler import crawl, load_config
from .models import CrawledPage, FactorResult, PageReport


def _text_length(value: str | None) -> int:
    return len(value.strip()) if value else 0


def _fold_text(value: str) -> str:
    folded = "".join(
        ch for ch in unicodedata.normalize("NFKD", value) if not unicodedata.combining(ch)
    )
    return re.sub(r"[^a-z0-9]+", "", folded.lower())


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
    """Extract image alt text coverage, distinguishing described, decorative, and missing images.

    Three classifications:
    - described:  alt attribute present and non-empty — the content image is correctly annotated.
    - decorative: alt attribute present but empty/whitespace (alt="") — intentional and correct;
                  excluded from scoring (Google Lighthouse treats this as valid).
    - missing:    no alt attribute at all — the genuine problem.

    Coverage = described / (described + missing). Decorative images are excluded entirely.
    pass >= 90 %, warn 50–89 %, fail < 50 %. If there are no content images (all decorative or
    no images at all) the result is pass with an explanatory note.
    """
    images = html.find_all("img")

    described = 0
    decorative = 0
    missing = 0
    for img in images:
        if "alt" not in img.attrs:
            missing += 1
        elif img["alt"].strip():
            described += 1
        else:
            decorative += 1

    relevant = described + missing  # decorative excluded

    value = {"described": described, "missing": missing, "decorative": decorative}

    if relevant == 0:
        note = "no images" if (described + missing + decorative) == 0 else "all images are decorative"
        return FactorResult(
            id="image_alt",
            status="pass",
            value=value,
            message=f"No content images require alt text ({note}).",
        )

    coverage = described / relevant

    # Build a consistent, readable message breakdown.
    missing_clause = f"{missing} missing the alt attribute"
    decorative_clause = (
        f" ({decorative} decorative image{'s' if decorative != 1 else ''} correctly use{'s' if decorative == 1 else ''} empty alt)"
        if decorative
        else ""
    )
    message = (
        f"{described} of {relevant} content image{'s' if relevant != 1 else ''} "
        f"{'have' if relevant != 1 else 'has'} descriptive alt text; "
        f"{missing_clause}{decorative_clause}."
    )

    if coverage >= 0.9:
        status = "pass"
    elif coverage >= 0.5:
        status = "warn"
    else:
        status = "fail"

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


# ---------------------------------------------------------------------------
# Additional HTML on-page factors (config-driven, weighted like the original seven).
# All are extractable from the existing crawl (BeautifulSoup over the fetched HTML);
# none require a paid SEO subscription.
# ---------------------------------------------------------------------------
def heading_structure(html: Any) -> FactorResult:
    """Sub-heading hierarchy beyond H1 (H2/H3 presence and order)."""
    h2 = html.find_all("h2")
    h3 = html.find_all("h3")
    if h2:
        # Flag an H3 that appears before any H2 (a skipped level).
        first_h2 = html.find("h2")
        first_h3 = html.find("h3")
        if first_h3 is not None and first_h2 is not None and _precedes(first_h3, first_h2):
            return FactorResult(id="heading_structure", status="warn",
                                value={"h2": len(h2), "h3": len(h3)},
                                message="An H3 appears before the first H2; keep headings in order (H2 → H3).")
        return FactorResult(id="heading_structure", status="pass",
                            value={"h2": len(h2), "h3": len(h3)},
                            message=f"Clear sub-heading structure ({len(h2)} H2, {len(h3)} H3).")
    if h3:
        return FactorResult(id="heading_structure", status="warn", value={"h2": 0, "h3": len(h3)},
                            message="H3 headings used without any H2; add H2 sections for a clear hierarchy.")
    return FactorResult(id="heading_structure", status="warn", value={"h2": 0, "h3": 0},
                        message="No H2/H3 sub-headings; structure the content with descriptive sub-headings.")


def open_graph(html: Any) -> FactorResult:
    """Open Graph tags (og:title / og:description / og:image) for rich social/AI previews."""
    present = [
        p for p in ("og:title", "og:description", "og:image")
        if html.find("meta", attrs={"property": p}) and
        (html.find("meta", attrs={"property": p}).get("content") or "").strip()
    ]
    if len(present) == 3:
        status, message = "pass", "Open Graph title, description and image are all present."
    elif present:
        status = "warn"
        message = f"Partial Open Graph tags ({', '.join(present)}); add the rest for richer previews."
    else:
        status, message = "fail", "No Open Graph tags; add og:title, og:description and og:image."
    return FactorResult(id="open_graph", status=status, value={"present": present}, message=message)


def twitter_card(html: Any) -> FactorResult:
    """Twitter card tags (twitter:card) for X/Twitter link previews."""
    tag = html.find("meta", attrs={"name": "twitter:card"})
    value = (tag.get("content") or "").strip() if tag else ""
    if value:
        return FactorResult(id="twitter_card", status="pass", value=value,
                            message="Twitter card metadata is present.")
    return FactorResult(id="twitter_card", status="warn", value=None,
                        message="No twitter:card tag; add Twitter card metadata for better link previews.")


def viewport_meta(html: Any) -> FactorResult:
    """Mobile viewport meta tag (responsive readiness)."""
    tag = html.find("meta", attrs={"name": "viewport"})
    content = (tag.get("content") or "").strip().lower() if tag else ""
    if "width=device-width" in content:
        return FactorResult(id="viewport_meta", status="pass", value=content,
                            message="Responsive viewport meta tag is present.")
    if content:
        return FactorResult(id="viewport_meta", status="warn", value=content,
                            message="Viewport tag present but not set to width=device-width for responsiveness.")
    return FactorResult(id="viewport_meta", status="fail", value=None,
                        message="No viewport meta tag; add one so the page renders well on mobile.")


def html_lang(html: Any) -> FactorResult:
    """`lang` attribute on <html> (accessibility + locale signal)."""
    tag = html.find("html")
    lang = (tag.get("lang") or "").strip() if tag else ""
    if lang:
        return FactorResult(id="html_lang", status="pass", value=lang,
                            message=f"Document language is declared (lang=\"{lang}\").")
    return FactorResult(id="html_lang", status="warn", value=None,
                        message="No lang attribute on <html>; declare the page language (e.g. lang=\"en\").")


def robots_meta(html: Any) -> FactorResult:
    """Robots meta directives — detect noindex/nofollow that block search/AI visibility."""
    tag = html.find("meta", attrs={"name": re.compile(r"^robots$", re.I)})
    content = (tag.get("content") or "").lower() if tag else ""
    if "noindex" in content:
        return FactorResult(id="robots_meta", status="fail", value=content,
                            message="Page is set to noindex; search engines/AI are told not to index it.")
    if "nofollow" in content:
        return FactorResult(id="robots_meta", status="warn", value=content,
                            message="Robots meta uses nofollow; links on this page won't pass authority.")
    return FactorResult(id="robots_meta", status="pass", value=content or "index,follow",
                        message="No restrictive robots meta directive (page is indexable).")


def internal_links(html: Any) -> FactorResult:
    """Internal-link presence/count (relative or in-page links) for crawl depth."""
    count = 0
    for a in html.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        parsed = urlparse(href)
        if not parsed.scheme and not href.startswith("//"):  # relative → internal
            count += 1
    if count >= 3:
        status, message = "pass", f"{count} internal links found, supporting site crawlability."
    elif count >= 1:
        status, message = "warn", f"Only {count} internal link(s); add more to connect related pages."
    else:
        status, message = "fail", "No internal links found; add navigation/contextual links between pages."
    return FactorResult(id="internal_links", status=status, value=count, message=message)


def favicon(html: Any) -> FactorResult:
    """Favicon link (brand polish in tabs and search results)."""
    tag = html.find("link", rel=lambda v: bool(v) and "icon" in (" ".join(v) if isinstance(v, list) else str(v)).lower())
    if tag and (tag.get("href") or "").strip():
        return FactorResult(id="favicon", status="pass", value=tag.get("href"),
                            message="A favicon is declared.")
    return FactorResult(id="favicon", status="warn", value=None,
                        message="No favicon link; add one for brand recognition in tabs and SERPs.")


def hreflang(html: Any) -> FactorResult:
    """hreflang alternate links (only relevant for multi-locale sites; informational)."""
    tags = html.find_all("link", rel=lambda v: bool(v) and "alternate" in (" ".join(v) if isinstance(v, list) else str(v)).lower())
    langs = [t for t in tags if (t.get("hreflang") or "").strip()]
    if langs:
        return FactorResult(id="hreflang", status="pass", value=len(langs),
                            message=f"{len(langs)} hreflang alternate(s) declared for international targeting.")
    return FactorResult(id="hreflang", status="warn", value=0,
                        message="No hreflang tags; add them only if the site serves multiple languages/regions.")


def _precedes(a: Any, b: Any) -> bool:
    """True if element ``a`` appears before ``b`` in document order."""
    for el in a.find_all_next():
        if el is b:
            return True
    return False


def factor_set_version(report) -> str:
    """Stable short id for the set of factor ids actually scored across a report.

    Lets trends detect when a report was scored with a DIFFERENT factor set (e.g. older
    reports predating new factors) and flag the comparison as low-confidence rather than a
    real delta. Derived from the data, so it changes automatically when factors are added.
    """
    import hashlib

    ids: set[str] = set()
    for page in getattr(report, "pages", []) or []:
        for f in getattr(page, "factors", []) or []:
            fid = getattr(f, "id", None)
            if fid:
                ids.add(str(fid))
    if not ids:
        return ""
    digest = hashlib.sha1(",".join(sorted(ids)).encode("utf-8")).hexdigest()[:8]
    return f"{len(ids)}-{digest}"


def _parse_html(html: str) -> Any:
    return BeautifulSoup(html, "lxml")


def crawl_access(page: CrawledPage) -> FactorResult:
    """Create an SEO factor for pages that could not be fetched as public HTML."""
    status = page.status_code if page.status_code is not None else "no response"
    error = page.error or f"HTTP {status}"
    return FactorResult(
        id="crawl_access",
        status="fail",
        value={"status_code": page.status_code, "error": error},
        message=(
            f"The page could not be audited for on-page SEO because the crawler received {status}. "
            "Make the public HTML accessible to legitimate crawlers or test a crawlable page path."
        ),
    )


def audit_coverage(page: CrawledPage) -> FactorResult:
    """Explain that this page is using limited URL/domain SEO checks."""
    return FactorResult(
        id="audit_coverage",
        status="warn",
        value={"mode": "fallback", "status_code": page.status_code},
        message=(
            "Fallback SEO audit used because page HTML was unavailable. URL/domain checks are shown, "
            "but title, meta description, H1, image ALT, word count, and schema still need crawlable HTML."
        ),
    )


def https_enabled(page: CrawledPage) -> FactorResult:
    parsed = urlparse(page.url)
    if parsed.scheme.lower() == "https":
        return FactorResult(
            id="https_enabled",
            status="pass",
            value={"scheme": parsed.scheme},
            message="The audited URL uses HTTPS.",
        )
    return FactorResult(
        id="https_enabled",
        status="fail",
        value={"scheme": parsed.scheme or None},
        message="The audited URL is not HTTPS; use HTTPS for crawlability, trust, and modern search requirements.",
    )


def domain_brand_signal(page: CrawledPage, config: dict[str, Any]) -> FactorResult:
    brand = str(config.get("site", {}).get("name", "")).strip()
    host = urlparse(page.url).netloc.lower().removeprefix("www.")
    brand_key = _fold_text(brand)
    host_key = _fold_text(host.split(":")[0])

    if not brand_key:
        return FactorResult(
            id="domain_brand_signal",
            status="warn",
            value={"brand": brand, "host": host},
            message="No brand name was configured, so brand/domain alignment could not be verified.",
        )
    if brand_key in host_key:
        return FactorResult(
            id="domain_brand_signal",
            status="pass",
            value={"brand": brand, "host": host},
            message="The configured brand is clearly reflected in the audited domain.",
        )

    return FactorResult(
        id="domain_brand_signal",
        status="warn",
        value={"brand": brand, "host": host},
        message=(
            "The configured brand is not obvious in the audited domain. If this is a parent, regional, "
            "or product URL, reinforce the brand with crawlable title tags, schema, and on-page copy."
        ),
    )


def canonical_url_shape(page: CrawledPage) -> FactorResult:
    parsed = urlparse(page.url)
    issues: list[str] = []
    if not parsed.scheme or not parsed.netloc:
        issues.append("missing scheme or host")
    if parsed.query:
        issues.append("query string present")
    if parsed.fragment:
        issues.append("fragment present")

    if not parsed.scheme or not parsed.netloc:
        status = "fail"
        message = "The audited URL is not a complete absolute URL; use a clean canonical HTTPS URL."
    elif issues:
        status = "warn"
        message = f"The audited URL is usable but not clean canonical shape ({', '.join(issues)})."
    else:
        status = "pass"
        message = "The audited URL is a clean absolute URL without query strings or fragments."

    return FactorResult(
        id="canonical_url_shape",
        status=status,
        value={"scheme": parsed.scheme, "host": parsed.netloc, "path": parsed.path, "issues": issues},
        message=message,
    )


def fallback_page_factors(page: CrawledPage, config: dict[str, Any]) -> list[FactorResult]:
    """Limited but useful SEO factors when page HTML cannot be audited."""
    return [
        crawl_access(page),
        audit_coverage(page),
        https_enabled(page),
        domain_brand_signal(page, config),
        canonical_url_shape(page),
    ]


def extract_page(page: CrawledPage, config: dict[str, Any]) -> PageReport:
    """Create a PageReport by running configured SEO factor extractors."""
    if page.status_code != 200 or not page.html:
        error = page.error or (f"HTTP {page.status_code}" if page.status_code else "No HTML returned")
        return PageReport(url=page.url, factors=fallback_page_factors(page, config), score=0.0, error=error)

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
        # Additional on-page factors (config-driven; added 2026-06).
        "heading_structure": heading_structure,
        "open_graph": open_graph,
        "twitter_card": twitter_card,
        "viewport_meta": viewport_meta,
        "html_lang": html_lang,
        "robots_meta": robots_meta,
        "internal_links": internal_links,
        "favicon": favicon,
        "hreflang": hreflang,
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

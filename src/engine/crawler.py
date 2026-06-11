"""Crawl website content and cache raw HTML pages."""

from __future__ import annotations

import hashlib
import re
import time
import urllib.robotparser
from pathlib import Path
from typing import Any
from urllib.parse import ParseResult, urljoin, urlparse, urlunparse

import requests
import yaml
from bs4 import BeautifulSoup

from .models import CrawledPage


def load_config(path: str = "config/crawl_config.yaml") -> dict[str, Any]:
    """Load crawler configuration from a YAML file.

    Args:
        path: Relative path to the YAML config file.

    Returns:
        A dictionary of crawler configuration values.
    """
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as stream:
        return yaml.safe_load(stream) or {}


def _normalize_url(url: str, base_url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme:
        url = urljoin(base_url, url)
    parsed = urlparse(url)
    return urlunparse(parsed._replace(fragment=""))


def _same_domain(url: str, base_netloc: str) -> bool:
    parsed_netloc = urlparse(url).netloc.lower().split(":")[0]
    return parsed_netloc == base_netloc.lower().split(":")[0]


def _filesystem_safe_filename(url: str) -> str:
    parsed = urlparse(url)
    candidate = f"{parsed.netloc}{parsed.path or '/'}"
    if parsed.query:
        candidate = f"{candidate}?{parsed.query}"
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", candidate).strip("_")
    suffix = hashlib.md5(url.encode("utf-8")).hexdigest()[:8]
    filename = f"{safe[:180]}_{suffix}.html"
    return filename or f"page_{suffix}.html"


def _extract_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href or href.startswith("mailto:") or href.startswith("javascript:"):
            continue
        normalized = _normalize_url(href, base_url)
        links.append(normalized)
    return links


def crawl(config: dict[str, Any]) -> list[CrawledPage]:
    """Crawl the configured website and cache HTML pages to data/raw/.

    Args:
        config: The parsed crawl configuration.

    Returns:
        A list of CrawledPage results.
    """
    site_config = config.get("site", {})
    crawl_config = config.get("crawl", {})

    base_url = site_config.get("base_url")
    if not base_url:
        raise ValueError("site.base_url is required in the crawl configuration")

    seed_urls = site_config.get("seed_urls", [])
    max_pages = int(crawl_config.get("max_pages", 15))
    max_depth = int(crawl_config.get("max_depth", 1))
    delay_seconds = float(crawl_config.get("delay_seconds", 1.0))
    user_agent = str(crawl_config.get("user_agent", "ai-search-engine-bot/0.1"))
    respect_robots = bool(crawl_config.get("respect_robots_txt", True))
    timeout_seconds = float(crawl_config.get("timeout_seconds", 10))

    raw_dir = Path("data/raw")
    raw_dir.mkdir(parents=True, exist_ok=True)

    base_netloc = urlparse(base_url).netloc
    robots_parser = None
    if respect_robots:
        robots_parser = urllib.robotparser.RobotFileParser()
        robots_url = _normalize_url("/robots.txt", base_url)
        robots_parser.set_url(robots_url)
        try:
            robots_parser.read()
        except Exception:
            robots_parser = None

    session = requests.Session()
    session.headers.update({"User-Agent": user_agent})

    queue: list[tuple[str, int]] = [(_normalize_url(url, base_url), 0) for url in seed_urls]
    visited: set[str] = set()
    results: list[CrawledPage] = []

    while queue and len(results) < max_pages:
        url, depth = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)

        if robots_parser and not robots_parser.can_fetch(user_agent, url):
            results.append(CrawledPage(url=url, status_code=None, html=None, error="blocked by robots.txt"))
            continue

        status_code = None
        html = None
        error_message = None

        try:
            response = session.get(url, timeout=timeout_seconds)
            status_code = response.status_code
            if response.ok:
                html = response.text
                filename = _filesystem_safe_filename(url)
                cache_path = raw_dir / filename
                cache_path.write_text(html, encoding="utf-8")
            else:
                error_message = f"HTTP {status_code}"
        except requests.RequestException as exc:
            error_message = str(exc)

        results.append(CrawledPage(url=url, status_code=status_code, html=html, error=error_message))

        if html and depth < max_depth:
            for link in _extract_links(html, base_url):
                if len(results) + len(queue) >= max_pages:
                    break
                if link in visited:
                    continue
                if _same_domain(link, base_netloc):
                    queue.append((link, depth + 1))

        if len(results) < max_pages:
            time.sleep(delay_seconds)

    return results


def main() -> None:
    config = load_config()
    results = crawl(config)
    success_count = sum(1 for page in results if page.status_code == 200)
    print(f"Pages attempted: {len(results)}")
    print(f"Successful fetches: {success_count}")
    for page in results:
        status = page.status_code if page.status_code is not None else page.error
        print(f"- {page.url} -> {status}")


if __name__ == "__main__":
    main()

"""Tests for the shared site-URL normaliser (src.engine.url_utils).

Fully offline. Runnable under pytest OR directly:

    .venv/bin/python -m tests.test_url_utils
"""

from __future__ import annotations

from src.engine.url_utils import normalise_site_url as n


def test_bare_domain_gets_https_and_trailing_slash() -> None:
    assert n("nandos.com.au") == "https://nandos.com.au/"
    assert n("www.nandos.com.au") == "https://www.nandos.com.au/"
    assert n("  nandos.com.au  ") == "https://nandos.com.au/"  # trimmed


def test_tracking_params_stripped_and_qmark_dropped() -> None:
    assert n("https://www.nandos.com.au/?gad_source=1&gclid=abc&gbraid=x") == "https://www.nandos.com.au/"
    assert n("https://x.com/?fbclid=1&msclkid=2&gad_campaignid=9") == "https://x.com/"


def test_utm_family_stripped_meaningful_kept() -> None:
    assert n("https://x.com/p?utm_source=g&utm_medium=cpc&id=42") == "https://x.com/p?id=42"


def test_path_case_preserved_host_lowered() -> None:
    assert n("HTTPS://WWW.Example.COM/Path/Case") == "https://www.example.com/Path/Case"
    assert n("www.nandos.com.au/menu") == "https://www.nandos.com.au/menu"  # no forced trailing slash


def test_fragment_stripped() -> None:
    assert n("https://x.com/page#section") == "https://x.com/page"


def test_invalid_rejected() -> None:
    for bad in ("", "   ", "not a url", "javascript:alert(1)", "ftp://x.com", "http://localhost"):
        try:
            n(bad)
            raise AssertionError(f"should have rejected {bad!r}")
        except ValueError:
            pass


def test_host_port_allowed() -> None:
    assert n("example.com:8080") == "https://example.com:8080/"


def _main() -> int:
    tests = [obj for name, obj in sorted(globals().items()) if name.startswith("test_")]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL  {t.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"ERROR {t.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    import sys

    sys.exit(_main())

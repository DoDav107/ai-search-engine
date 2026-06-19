"""Throwaway live-mode validation harness for the GEO brand-detection pipeline.

Run from the repo root:
    python validate_geo.py

Requires OPENAI_API_KEY in .env or the environment.
"""

from src.clients.openai_client import client
from src.agents.geo_agent import GeoQueryResult, detect_brand_mentions

QUERY = "What are some popular note-taking apps?"
KNOWN_BRAND = "Notion"        # should appear in any reasonable answer
PHANTOM_BRAND = "Zxqwprt"    # impossible brand — must never appear

# ---------------------------------------------------------------------------

def check(label: str, answer: str, brand: str, expect_found: bool) -> None:
    result = GeoQueryResult(query=QUERY, engine="openai", answer=answer)
    detect_brand_mentions(result, brand, competitors=[])

    found = result.brand_mentioned
    passed = found == expect_found
    status = "PASS" if passed else "FAIL"
    found_str = f"detected ({result.mention_count}x)" if found else "not detected"

    print(f"\n{'='*60}")
    print(f"[{status}]  {label}")
    print(f"  Brand checked : {brand!r}")
    print(f"  Expected      : {'found' if expect_found else 'not found'}")
    print(f"  Actual        : {found_str}")
    print(f"  AI response   : {answer[:300]}{'...' if len(answer) > 300 else ''}")


print(f"Sending query: {QUERY!r}")
answer = client.chat(QUERY)

check("Known-positive — Notion should appear", answer, KNOWN_BRAND,  expect_found=True)
check("Known-negative — Zxqwprt must not appear", answer, PHANTOM_BRAND, expect_found=False)
print(f"\n{'='*60}")
print(f"API calls used: {client.call_count}")

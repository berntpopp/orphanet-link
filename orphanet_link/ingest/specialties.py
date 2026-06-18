"""Orphadata product-3 medical-specialty classification IDs and filenames.

Provides the committed list of known specialty IDs and a helper that maps each
ID to its ``en_product3_<id>.xml`` filename.  An optional scraper
(``refresh_specialty_ids``) can be imported and called at runtime if Playwright
is available, but the module itself never requires it.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: Known Orphadata product-3 medical-specialty classification IDs.
#: These correspond to ``en_product3_<id>.xml`` files on orphadata.com.
SPECIALTY_IDS: list[str] = [
    "146", "147", "148", "149", "150", "156", "181", "182", "183", "184",
    "185", "186", "187", "188", "189", "192", "193", "194", "195", "196",
    "199", "200", "202", "203", "204", "205", "206", "207", "209", "212",
    "213", "216", "231",
]


def product3_filenames() -> dict[str, str]:
    """Return a map of specialty_id -> ``en_product3_<id>.xml`` filename."""
    return {sid: f"en_product3_{sid}.xml" for sid in SPECIALTY_IDS}


def refresh_specialty_ids() -> list[str]:
    """Scrape https://www.orphadata.com/classifications/ for product-3 IDs.

    Requires Playwright (``pip install playwright`` + ``playwright install``).
    Raises ``ImportError`` if Playwright is not installed.

    Returns:
        Sorted list of specialty ID strings found on the page.
    """
    try:
        from playwright.sync_api import sync_playwright  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "Playwright is not installed. "
            "Run `pip install playwright && playwright install` to enable scraping."
        ) from exc

    import re

    ids: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://www.orphadata.com/classifications/", timeout=30000)
        page.wait_for_load_state("networkidle")
        links = page.eval_on_selector_all(
            "a[href]",
            "elements => elements.map(el => el.href)",
        )
        for href in links:
            match = re.search(r"en_product3_(\d+)\.xml", href)
            if match:
                ids.append(match.group(1))
        browser.close()

    unique = sorted(set(ids), key=int)
    logger.info("refresh_specialty_ids found %d specialty IDs", len(unique))
    return unique

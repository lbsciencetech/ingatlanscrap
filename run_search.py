"""Open ingatlan.com in Camoufox, fill the search form, run the search.

Setup (once):
    python -m venv .venv
    .venv/bin/pip install camoufox
    .venv/bin/python -m camoufox fetch

Run:
    .venv/bin/python run_search.py                       # headless, prints JSON
    .venv/bin/python run_search.py --screenshots shots/  # + JPEG captures
"""
from __future__ import annotations

import argparse
import base64
import copy
import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from camoufox.sync_api import Camoufox
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PWTimeout

from fillform import fill_search_form, validate


def log(*args) -> None:
    """Progress messages go to stderr: stdout is reserved for the MCP
    protocol when this module runs inside mcp_server.py."""
    print(*args, file=sys.stderr, flush=True)


START_URL = "https://ingatlan.com/"

# The site uses Cookiebot; the banner doesn't always show (e.g. headless).
COOKIE_ACCEPT = (
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll, "
    "#CybotCookiebotDialogBodyButtonAccept, "
    'button:has-text("Összes engedélyezése"), '
    'button:has-text("Elfogadom")'
)
INTERSTITIAL_CLOSE = '[id="interstitial-close-button"]'
SUBMIT_BUTTON = '[data-testid="search-button"]'

# Every key the form understands. None = leave untouched.
# Replace get_search_data() later with your own source.
SEARCH_DATA: dict = {
    # ── main bar ─────────────────────────────────────────────
    "listingType": "sale",              # "sale" | "rent"
    "propertyType": "flat",             # flat|house|plot|garage|holiday|office|shop|catering
                                        # |warehouse|industrial|agricultural|developmentArea|institute
    "location": "Budapest, XI. kerület",  # str | list[str] | None
    "priceFrom": 40,                    # million Ft
    "priceTo": 90,
    "areaFrom": 50,                     # m²
    "areaTo": 100,
    "roomsFrom": 2,
    "roomsTo": None,
    "wekerlePlusLoan": None,            # bool | None
    "newlyBuilt": None,                 # bool | None

    # ── detailed panel: checkbox groups ([] or "any" = mindegy, None = untouched)
    "propertySubtype": ["brickFlat"],   # brickFlat, blockOfFlats, slipFormed
    "condition": ["renovated", "inGoodCondition", "looksLikeNew"],
    "yearOfConstruction": [],           # before1950, between1950And1980, between1981And2000,
                                        # between2001And2010, after2011
    "view": [],                         # yard, street, panoramic, garden
    "orientation": [],                  # north, northEast, east, southEast, south,
                                        # southWest, west, northWest
    "heatingType": [],                  # see fillform.CHECKBOX_GROUPS["heatingType"]
    "parking": [],                      # outdoor, indoor, garage, street
    "comfortLevel": [],                 # luxury, double, full, comfortable, half, none
    "atticType": [],                    # attic, notAttic, topFloor, closingLevel, penthouse
    "bathroomToiletSeparation": [],     # separately, together, both

    # ── detailed panel: selects (value attribute of the <option>)
    "floorFrom": None,                  # semiBasement|ground|mezzanine|first|second|third|fourth
                                        # |fifth|sixth|seventh|eight (sic)|ninth|tenth|aboveTen
    "floorTo": None,
    "innerHeight": None,                # any|normal|high

    # ── detailed panel: radios (True = "van" | "any" = mindegy | None = untouched)
    #    NB: the site has no "nincs" (= no) option, so False is rejected.
    "hasElevator": None,
    "hasBalcony": True,
    "hasInsulation": None,
    "isEnergyEfficient": None,
    "hasBarrierFreeAccess": None,
    "hasAirConditioner": None,
    "hasGardenAccess": None,
    "participatedInThePanelProgram": None,

    # ── detailed panel: misc
    "euroPriceFrom": None,              # thousand € — EXCLUSIVE with priceFrom/priceTo
    "euroPriceTo": None,
    "containsKeyword": None,            # str | None
    "excludesKeyword": None,
    "hasPhoto": True,                   # bool | None
    "hasLocalGovernmentAdvertiser": None,
    "isRentalRightOffer": None,
}


def get_search_data() -> dict:
    """Placeholder: swap for your real data source later."""
    return copy.deepcopy(SEARCH_DATA)


def _click_if_visible(page: Page, selector: str, timeout: int) -> bool:
    loc = page.locator(selector).first
    try:
        loc.wait_for(state="visible", timeout=timeout)
    except PWTimeout:
        return False
    loc.click()
    return True


def dismiss_overlays(page: Page) -> None:
    """Cookie banner and full-page ad, if they show up (both are optional)."""
    if _click_if_visible(page, COOKIE_ACCEPT, timeout=4_000):
        log("[ok] cookies accepted")
    if _click_if_visible(page, INTERSTITIAL_CLOSE, timeout=500):
        log("[ok] interstitial closed")


def submit(page: Page) -> str:
    old_url = page.url
    page.locator(SUBMIT_BUTTON).first.click()
    try:
        page.wait_for_url(lambda u: u != old_url, timeout=20_000)
    except PWTimeout:
        raise RuntimeError("search did not navigate to a results page") from None
    page.wait_for_load_state("domcontentloaded")
    return page.url


# ---------- results scraping ------------------------------------------------

LISTING_CARD = 'a[data-testid="listing-card"]'
PAGE_SIZE = 20  # cards per results page on ingatlan.com

# Runs in the page: one plain object per listing card.
_EXTRACT_CARDS_JS = r"""
cards => cards.map(a => {
  const txt = el => el ? el.textContent.replace(/\s+/g, ' ').trim() : null;
  const content = a.querySelector('.listing-card-content');
  const details = {};
  content?.querySelectorAll('div.d-flex.flex-column').forEach(d => {
    const s = d.querySelectorAll(':scope > span');
    if (s.length === 2) details[txt(s[0])] = txt(s[1]);
  });
  const img = a.querySelector('img.listing-card-image')?.getAttribute('src') || null;
  // After the real results, the site appends "extended" listings that do NOT
  // match the search (e.g. another district): flag them so they're dropped.
  const extended =
    a.getAttribute('data-listings-page--results-listing-is-extended-listing-value') === 'true' ||
    !!a.closest('[data-listings-page--extended-list-hidden-class]');
  return {
    extended,
    id: a.dataset.listingId || null,
    href: a.getAttribute('href'),
    price: txt(content?.querySelector('span.fw-bold.fs-5')),
    price_per_m2: txt(a.querySelector('.listing-card-area-prices')),
    address: txt(content?.querySelector('span.d-block.fs-7')),
    details,
    image: img && !img.includes('listing-image-error') ? img : null,
    labels: [...a.querySelectorAll('[data-testid="listing-label"]')].map(txt).filter(Boolean),
  };
})
"""


def _page_url(url: str, page_no: int) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    query["page"] = str(page_no)
    return urlunsplit(parts._replace(query=urlencode(query)))


def _total_results(page: Page) -> int | None:
    """Total from the heading, e.g. "Eladó XI. kerületi lakások 26 találat"."""
    m = re.search(r"(\d[\d\s ]*)\s*találat", page.locator("body").inner_text())
    return int(re.sub(r"\D", "", m.group(1))) if m else None


def _wait_for_results(page: Page) -> bool:
    """True if listing cards are shown, False for an empty result list."""
    try:
        page.locator(LISTING_CARD).first.wait_for(state="attached", timeout=10_000)
        return True
    except PWTimeout:
        return False


def _clean(raw: dict) -> dict:
    details = {k: v for k, v in (raw.get("details") or {}).items() if k and v}
    return {
        "id": raw.get("id"),
        "url": urljoin(START_URL, raw.get("href") or ""),
        "price": raw.get("price"),
        "price_per_m2": raw.get("price_per_m2"),
        "address": raw.get("address"),
        "area": details.get("Alapterület"),
        "rooms": details.get("Szobák"),
        "details": details,                 # every label/value shown on the card
        "image": raw.get("image"),
        "labels": raw.get("labels") or [],
    }


def scrape_results(page: Page, max_results: int) -> dict:
    """Scrape the listing cards of the current results page, following the
    pagination until `max_results` listings are collected."""
    base_url = page.url
    total = _total_results(page)
    listings: list[dict] = []
    seen: set[str] = set()
    page_no = 1
    while len(listings) < max_results:
        if not _wait_for_results(page):
            break
        raw_cards = page.locator(LISTING_CARD).evaluate_all(_EXTRACT_CARDS_JS)
        matching = [c for c in raw_cards if not c.get("extended")]
        new = [c for c in matching if c.get("href") and c["href"] not in seen]
        if not new:                         # past the last page
            break
        for card in new:
            seen.add(card["href"])
            listings.append(_clean(card))
        log(f"[ok] page {page_no}: {len(new)} listings (total so far {len(listings)})")
        reached_end = (len(matching) < PAGE_SIZE                  # short or extended page
                       or (total is not None and len(listings) >= total))
        if reached_end:
            break
        page_no += 1
        page.goto(_page_url(base_url, page_no), wait_until="domcontentloaded", timeout=60_000)
    return {"total": total, "listings": listings[:max_results]}


def _screenshot(page: Page, name: str, *, full_page: bool) -> dict:
    """JPEG screenshot, base64-encoded so it can travel in JSON."""
    data = page.screenshot(type="jpeg", quality=60, full_page=full_page)
    log(f"[ok] screenshot: {name} ({len(data) // 1024} KB)")
    return {"name": name, "mime": "image/jpeg", "data": base64.b64encode(data).decode("ascii")}


def run(data: dict, *, max_results: int = 0, screenshots: bool = False) -> dict:
    """Fill the form, run the search, and (if max_results > 0) scrape the
    results. The browser always runs headless; with `screenshots`, JPEG
    captures of the filled form and of the results page are returned.

    Returns {"url", "total", "listings", "screenshots"}."""
    validate(data)  # fail fast, before launching the browser
    shots: list[dict] = []
    with Camoufox(headless=True, humanize=True, locale="hu-HU") as browser:
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.set_default_timeout(15_000)
        page.goto(START_URL, wait_until="domcontentloaded", timeout=60_000)
        dismiss_overlays(page)

        fill_search_form(page, data)
        if screenshots:
            page.evaluate("window.scrollTo(0, 0)")
            shots.append(_screenshot(page, "Filled search form", full_page=True))

        result_url = submit(page)
        log(f"[ok] results: {result_url}")
        if screenshots:
            _wait_for_results(page)
            shots.append(_screenshot(page, "Results page", full_page=False))

        scraped = {"total": None, "listings": []}
        if max_results > 0:
            scraped = scrape_results(page, max_results)
            log(f"[ok] scraped {len(scraped['listings'])} of {scraped['total']} listings")

        return {"url": result_url, **scraped, "screenshots": shots}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-results", type=int, default=20, help="listings to scrape (0 = none)")
    ap.add_argument("--screenshots", metavar="DIR", help="save screenshots (JPEG) into DIR")
    args = ap.parse_args()
    out = run(get_search_data(), max_results=args.max_results, screenshots=bool(args.screenshots))
    for i, shot in enumerate(out.pop("screenshots"), 1):
        path = Path(args.screenshots) / f"{i}-{shot['name'].lower().replace(' ', '-')}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(shot["data"]))
        log(f"[ok] saved {path}")
    print(json.dumps(out, ensure_ascii=False, indent=2))

"""Fill the ingatlan.com search form (main bar + detailed panel) with Playwright.

Works with any Playwright-compatible Page (plain Playwright or Camoufox).

Conventions for the `data` dict (see SEARCH_DATA in run_search.py):
    * None            -> leave the field untouched
    * [] / "any"      -> "mindegy" (any) for checkbox groups
    * True / False    -> ticked / unticked for single checkboxes
    * True / "any"    -> "van" / "mindegy" for the yes/no radios
                         (the site has no "nincs" option)
"""
from __future__ import annotations

import re
import sys

from playwright.sync_api import Locator, Page, expect


def log(*args) -> None:
    """Progress messages go to stderr: stdout is reserved for the MCP
    protocol when this module runs inside mcp_server.py."""
    print(*args, file=sys.stderr, flush=True)


# ---------- schema ----------------------------------------------------------

CHECKBOX_GROUPS: dict[str, list[str]] = {
    "propertySubtype": ["brickFlat", "blockOfFlats", "slipFormed"],
    "condition": ["newlyBuilt", "looksLikeNew", "renovated", "inGoodCondition",
                  "inMediumCondition", "toBeRenovated", "incomplete"],
    "yearOfConstruction": ["before1950", "between1950And1980", "between1981And2000",
                           "between2001And2010", "after2011"],
    "view": ["yard", "street", "panoramic", "garden"],
    "orientation": ["north", "northEast", "east", "southEast", "south",
                    "southWest", "west", "northWest"],
    "heatingType": ["gasConvector", "houseCentral", "houseCentralWithIndividualMeasuring",
                    "district", "districtWithIndividualMeasuring", "electricConvector",
                    "electricHeatingPanel", "electricBoiler", "airConditioner", "infra",
                    "fireplace", "stove", "fanCoil", "gasBoiler", "mixedBoiler",
                    "otherHouseCentral", "tileStove", "floorHeating", "wallHeating",
                    "ceilingHeatingCooling", "heatPump", "other", "noHeating"],
    "parking": ["outdoor", "indoor", "garage", "street"],
    "comfortLevel": ["luxury", "double", "full", "comfortable", "half", "none"],
    "atticType": ["attic", "notAttic", "topFloor", "closingLevel", "penthouse"],
    "bathroomToiletSeparation": ["separately", "together", "both"],
}

RADIO_FIELDS = [
    "hasElevator", "hasBalcony", "hasInsulation", "isEnergyEfficient",
    "hasBarrierFreeAccess", "hasAirConditioner", "hasGardenAccess",
    "participatedInThePanelProgram",
]

BOOLEAN_FIELDS = ["hasPhoto", "hasLocalGovernmentAdvertiser", "isRentalRightOffer"]

LISTING_TYPES = {"sale", "rent"}

PROPERTY_TYPES = {"flat", "house", "plot", "garage", "holiday", "office", "shop",
                  "catering", "warehouse", "industrial", "agricultural",
                  "developmentArea", "institute"}

MAIN_RANGES = {   # key -> data-testid
    "priceFrom": "price-range-from", "priceTo": "price-range-to",
    "areaFrom": "area-range-from", "areaTo": "area-range-to",
    "roomsFrom": "room-range-from", "roomsTo": "room-range-to",
}
MAIN_CHECKBOXES = {"wekerlePlusLoan": "wekerlePlusLoanField",
                   "newlyBuilt": "newlyBuiltField"}
# <option> values as served by the site (note: "eight", not "eighth")
FLOOR_VALUES = {"semiBasement", "ground", "mezzanine", "first", "second", "third",
                "fourth", "fifth", "sixth", "seventh", "eight", "ninth", "tenth",
                "aboveTen"}
INNER_HEIGHT_VALUES = {"any", "normal", "high"}
SELECT_FIELDS = {"floorFrom": FLOOR_VALUES, "floorTo": FLOOR_VALUES,
                 "innerHeight": INNER_HEIGHT_VALUES}
NUMBER_FIELDS = [*MAIN_RANGES, "euroPriceFrom", "euroPriceTo"]
TEXT_FIELDS = ["containsKeyword", "excludesKeyword"]

ALL_KEYS = ({"listingType", "propertyType", "location"} | set(MAIN_RANGES)
            | set(MAIN_CHECKBOXES) | set(CHECKBOX_GROUPS) | set(SELECT_FIELDS)
            | set(RADIO_FIELDS) | {"euroPriceFrom", "euroPriceTo"}
            | set(TEXT_FIELDS) | set(BOOLEAN_FIELDS))

# Selectors checked against the live site (Nov 2026). Adjust here if it changes.
DETAILED_PANEL_TOGGLER = "button.detailedSearchButton"     # "Részletes kereső"
LOC_MAIN_INPUT = '[data-testid="searcher-form"] [data-testid="searcher-input"]'
LOC_MODAL = '[data-testid="location-selector-box"]'
LOC_MODAL_INPUT = f'{LOC_MODAL} [data-testid="autosuggest-input"]'
LOC_SUGGESTION = f'{LOC_MODAL} [data-testid="autosuggest-suggestion"]'
LOC_MODAL_TAG = f'{LOC_MODAL} [data-testid="autosuggest-selected-tag"]'
LOC_MODAL_TAG_REMOVE = f'{LOC_MODAL} [data-testid="autosuggest-remove"]'
LOC_MODAL_SUBMIT = '[data-testid="location-selector-submit"]'   # "Rendben"

DEFAULT_TIMEOUT = 5_000   # ms


# ---------- validation ------------------------------------------------------

def validate(data: dict) -> None:
    """Raise ValueError listing every problem in `data` (typos, bad values…)."""
    errors: list[str] = []

    unknown = set(data) - ALL_KEYS
    if unknown:
        errors.append(f"unknown keys: {sorted(unknown)}")
    missing = ALL_KEYS - set(data)
    if missing:
        errors.append(f"missing keys (use None to skip): {sorted(missing)}")

    def check_enum(key, allowed):
        v = data.get(key)
        if v is not None and v not in allowed:
            errors.append(f"{key}={v!r} not in {sorted(allowed)}")

    check_enum("listingType", LISTING_TYPES)
    check_enum("propertyType", PROPERTY_TYPES)

    loc = data.get("location")
    if loc is not None and not (
        isinstance(loc, str)
        or (isinstance(loc, list) and all(isinstance(x, str) for x in loc))
    ):
        errors.append("location must be a str, a list of str, or None")

    for key in NUMBER_FIELDS:
        v = data.get(key)
        if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0):
            errors.append(f"{key}={v!r} must be a non-negative number or None")
    for lo, hi in (("priceFrom", "priceTo"), ("areaFrom", "areaTo"),
                   ("roomsFrom", "roomsTo"), ("euroPriceFrom", "euroPriceTo")):
        a, b = data.get(lo), data.get(hi)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and a > b:
            errors.append(f"{lo} ({a}) > {hi} ({b})")

    huf = data.get("priceFrom") is not None or data.get("priceTo") is not None
    eur = data.get("euroPriceFrom") is not None or data.get("euroPriceTo") is not None
    if huf and eur:
        errors.append("priceFrom/priceTo (HUF) and euroPriceFrom/euroPriceTo are "
                      "mutually exclusive on the site: set one pair to None")

    for key in RADIO_FIELDS:
        v = data.get(key)
        if v is not None and v is not True and v != "any":
            errors.append(f"{key}={v!r}: the site only offers 'van' (True) or "
                          f"'mindegy' (\"any\"); there is no 'no' filter")

    for key in [*MAIN_CHECKBOXES, *BOOLEAN_FIELDS]:
        v = data.get(key)
        if v is not None and not isinstance(v, bool):
            errors.append(f"{key}={v!r} must be True, False or None")

    for group, options in CHECKBOX_GROUPS.items():
        v = data.get(group)
        if v is None or v == "any":
            continue
        values = [v] if isinstance(v, str) else v
        if not isinstance(values, list):
            errors.append(f"{group} must be a list, a str, 'any' or None")
            continue
        bad = [x for x in values if x != "any" and x not in options]
        if bad:
            errors.append(f"{group}: invalid {bad}; allowed {options}")

    for key, allowed in SELECT_FIELDS.items():
        check_enum(key, allowed)
    order = ["semiBasement", "ground", "mezzanine", "first", "second", "third",
             "fourth", "fifth", "sixth", "seventh", "eight", "ninth", "tenth", "aboveTen"]
    f, t = data.get("floorFrom"), data.get("floorTo")
    if f in order and t in order and order.index(f) > order.index(t):
        errors.append(f"floorFrom ({f}) is above floorTo ({t})")

    for key in TEXT_FIELDS:
        v = data.get(key)
        if v is not None and not isinstance(v, str):
            errors.append(f"{key}={v!r} must be a str or None")

    if errors:
        raise ValueError("Invalid search data:\n  - " + "\n  - ".join(errors))


# ---------- low-level helpers -----------------------------------------------

def _input(page: Page, element_id: str) -> Locator:
    # The site reuses ids on wrapper <div>s (e.g. two id="innerHeight"), so
    # always target the element type explicitly.
    return page.locator(f'input[id="{element_id}"]').first


def _toggle_input(page: Page, inp: Locator, input_id: str, checked: bool) -> None:
    """Set a visually hidden checkbox/radio and verify the result.

    1st try: click the visible <label for=…> like a user would.
    Fallback: native el.click() via JS (fires the events Vue listens to,
    even though the input itself has no layout box).
    """
    if inp.is_checked() == checked:
        return
    lbl = page.locator(f'label[for="{input_id}"]:visible').first
    if lbl.count() > 0:
        lbl.scroll_into_view_if_needed()
        lbl.click()
        try:
            expect(inp).to_be_checked(checked=checked, timeout=1_500)
            return
        except AssertionError:
            pass
    if inp.is_checked() != checked:
        inp.evaluate("el => el.click()")
    expect(inp).to_be_checked(checked=checked, timeout=DEFAULT_TIMEOUT)


def _set_checkbox(page: Page, input_id: str, checked: bool, *, required: bool = False) -> bool:
    """Returns False if the checkbox doesn't exist (some options disappear
    depending on propertyType). Raises if `required` and it is missing."""
    inp = _input(page, input_id)
    if inp.count() == 0:
        if required:
            raise LookupError(f"input #{input_id} not found")
        log(f"[skip] #{input_id} not present for this property type")
        return False
    _toggle_input(page, inp, input_id, checked)
    return True


def _set_radio(page: Page, field: str, value) -> None:
    # "<field>-checked" = "van", "<field>-unchecked" = "mindegy"
    target_id = f"{field}-checked" if value is True else f"{field}-unchecked"
    inp = _input(page, target_id)
    if inp.count() == 0:
        log(f"[skip] radio {field} not present for this property type")
        return
    _toggle_input(page, inp, target_id, True)


def _select(page: Page, element_id: str, value: str) -> None:
    """select_option with a clear error message listing the valid values."""
    sel = page.locator(f'select[id="{element_id}"]').first
    sel.wait_for(state="attached", timeout=DEFAULT_TIMEOUT)
    options = sel.evaluate("el => Array.from(el.options).map(o => o.value)")
    if value not in options:
        raise ValueError(f"#{element_id}: {value!r} not in available options {options}")
    sel.scroll_into_view_if_needed()
    sel.select_option(value)
    expect(sel).to_have_value(value)


def _fill(loc: Locator, value) -> None:
    loc.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
    if not loc.is_enabled():
        raise RuntimeError(f"field {loc} is disabled (conflicting option set?)")
    loc.scroll_into_view_if_needed()
    text = str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)
    loc.fill(text)
    expect(loc).to_have_value(text)


def _expand(page: Page, group: str) -> None:
    """Unfold a `.searcherExpandable` group if it is closed (its options
    are only rendered once it is open)."""
    container = page.locator(f'[data-testid="{group}"]').first
    if container.count() == 0:
        return
    if re.search(r"\bopened\b", container.get_attribute("class") or ""):
        return
    toggler = page.locator(f'[data-testid="{group}-toggler"]').first
    opened = re.compile(r"\bopened\b")
    # The 1st click can be swallowed while the detailed panel is still
    # animating open, so retry a few times.
    for attempt in range(3):
        toggler.scroll_into_view_if_needed()
        toggler.click()
        try:
            expect(container).to_have_class(opened, timeout=1_500)
            break
        except AssertionError:
            page.wait_for_timeout(300)
            if opened.search(container.get_attribute("class") or ""):
                break          # opened late: don't click again (would close it)
            if attempt == 2:
                raise RuntimeError(f"could not expand group {group!r}") from None
    page.locator(f'input[id="{group}-any"]').first.wait_for(state="attached",
                                                         timeout=DEFAULT_TIMEOUT)


def _open_detailed_panel(page: Page) -> None:
    """Make sure the detailed panel is visible (its fields live there)."""
    marker = page.locator('[id="containsKeyword"]').first
    if marker.count() > 0 and marker.is_visible():
        return
    toggler = page.locator(DETAILED_PANEL_TOGGLER).first
    toggler.scroll_into_view_if_needed()
    toggler.click()
    marker.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)


def _norm(s: str) -> str:
    return " ".join(s.replace("\n", " ").replace(",", " ").split()).casefold()


def _stable_suggestions(page: Page, rounds: int = 25) -> list[str]:
    """Return the suggestion texts once the list stops changing (the list is
    re-rendered after each keystroke's request comes back)."""
    sugs = page.locator(LOC_SUGGESTION)
    prev = None
    for _ in range(rounds):                     # ~ rounds * 250 ms
        page.wait_for_timeout(250)
        cur = sugs.all_inner_texts()
        if cur and cur == prev:
            return cur
        prev = cur
    return prev or []


def _pick_suggestion(page: Page, query: str) -> str:
    """Click the suggestion matching `query`.

    A suggestion's text is "<label>" or "<label>\n<parent>" (e.g.
    "Sasad\nBudapest XI. kerület"). Exact match on the label or on
    "label, parent" wins; otherwise the first suggestion is taken with a
    warning.
    """
    target = _norm(query)
    texts = _stable_suggestions(page)
    if not texts:
        raise LookupError(f"no location suggestion for {query!r}")
    idx = next((i for i, t in enumerate(texts)
                if target in (_norm(t), _norm(t.split("\n")[0]))), None)
    if idx is None:
        log(f"[warn] no exact match for {query!r}; taking {texts[0]!r}")
        idx = 0
    page.locator(LOC_SUGGESTION).nth(idx).click()
    return texts[idx]


def _fill_locations(page: Page, values: list[str]) -> None:
    """Location = modal dialog: click the main input, type in the modal's
    own input, pick suggestions (each becomes a tag), then confirm with
    "Rendben". Escape/"Mégsem" would DISCARD the selection."""
    page.locator(LOC_MAIN_INPUT).first.click()
    modal_input = page.locator(LOC_MODAL_INPUT).first
    modal_input.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)

    tags = page.locator(LOC_MODAL_TAG)
    while tags.count() > 0:                     # start from a clean selection
        n = tags.count()
        page.locator(LOC_MODAL_TAG_REMOVE).first.click()
        expect(tags).to_have_count(n - 1)

    for value in values:
        n = tags.count()
        for attempt in (1, 2):
            modal_input.click()
            # NEVER fill("") / Backspace here: emptying the field makes the
            # widget drop every selected tag. It is already empty after a
            # pick; if not, select the leftover text so typing replaces it.
            if modal_input.input_value():
                modal_input.press("Control+a")
            modal_input.press_sequentially(value, delay=60)
            picked = _pick_suggestion(page, value)
            try:
                expect(tags).to_have_count(n + 1, timeout=3_000)
                break
            except AssertionError:
                if attempt == 2:
                    raise RuntimeError(
                        f"location {value!r} was not added "
                        f"(tags: {tags.all_inner_texts()})") from None
                log(f"[retry] location {value!r} not registered, retrying")
        log(f"[ok] location: {picked.splitlines()[0]}")

    page.locator(LOC_MODAL_SUBMIT).first.click()
    page.locator(LOC_MODAL).first.wait_for(state="hidden", timeout=DEFAULT_TIMEOUT)


# ---------- main ------------------------------------------------------------

def fill_search_form(page: Page, data: dict) -> None:
    """Fill the ingatlan.com form (main bar + detailed panel). Validates first."""
    validate(data)

    # ---------- 1) MAIN BAR ----------

    # 1.a Sale / rent (hidden radios -> click the <label>)
    if data["listingType"] is not None:
        _set_checkbox(page, data["listingType"], True, required=True)

    # 1.b Property type — BEFORE the detailed panel: some panel options
    #     depend on it (e.g. brickFlat only exists for "flat").
    if data["propertyType"] is not None:
        _select(page, "propertyType", data["propertyType"])
        # the panel re-renders for the new type: wait for it to settle
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(300)

    # 1.c Location(s) (autocomplete)
    locations = data["location"]
    if isinstance(locations, str):
        locations = [locations]
    if locations:
        _fill_locations(page, locations)

    # 1.d Price / area / rooms
    for key, testid in MAIN_RANGES.items():
        if data[key] is not None:
            _fill(page.locator(f'[data-testid="{testid}"]').first, data[key])

    # 1.e Main bar checkboxes
    for key, input_id in MAIN_CHECKBOXES.items():
        if data[key] is not None:
            _set_checkbox(page, input_id, data[key])

    # ---------- 2) DETAILED PANEL ----------
    _open_detailed_panel(page)

    # 2.a Checkbox groups.
    # Order matters: check wanted options first, then uncheck the others,
    # and only then "any" — many widgets re-tick "any" when the group
    # becomes empty, or untick options when "any" is ticked.
    for group, options in CHECKBOX_GROUPS.items():
        selected = data[group]
        if selected is None:
            continue
        if isinstance(selected, str):
            selected = [selected]
        selected = [s for s in selected if s != "any"]

        _expand(page, group)
        any_id = f"{group}-any"
        if not selected:
            _set_checkbox(page, any_id, True)
            continue
        for opt in options:
            if opt in selected:
                _set_checkbox(page, f"{group}-{opt}", True)
        for opt in options:
            if opt not in selected:
                _set_checkbox(page, f"{group}-{opt}", False)
        any_inp = _input(page, any_id)
        if any_inp.count() > 0 and any_inp.is_checked():
            _set_checkbox(page, any_id, False)

    # 2.b Selects
    for field in SELECT_FIELDS:
        if data[field] is not None:
            _select(page, field, data[field])

    # 2.c "van / mindegy" radios
    for field in RADIO_FIELDS:
        if data[field] is not None:
            _set_radio(page, field, data[field])

    # 2.d Euro price (both inputs share data-testid="range-input-from";
    #     they are distinguished by their min./max. placeholder)
    for key, ph in (("euroPriceFrom", "min."), ("euroPriceTo", "max.")):
        if data[key] is not None:
            _fill(page.locator(f'[data-testid="range-input-from"][placeholder="{ph}"]').first,
                  data[key])

    # 2.e Text fields
    for field in TEXT_FIELDS:
        if data[field] is not None:
            _fill(page.locator(f'textarea[id="{field}"], input[id="{field}"]').first,
                  data[field])

    # 2.f Single checkboxes
    for field in BOOLEAN_FIELDS:
        if data[field] is not None:
            _set_checkbox(page, field, data[field])

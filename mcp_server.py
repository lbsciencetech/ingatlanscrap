"""MCP server: turn a plain-language flat description into an ingatlan.com search.

Tool `search_flats(description)`:
  1. asks Claude (with the SERVER's own API key) to translate the description
     into the search dict understood by fillform.py,
  2. validates it; if invalid, asks again with the error messages
     (up to MAX_ATTEMPTS),
  3. fills the form in Camoufox, then scrapes the result listings (price,
     address, area, rooms, photo, link…) and returns them (skip with dry_run).
     The browser always runs headless; ask for `screenshots` to see it.

API key, in order of priority:
  1. INGATLAN_CLIENT_API_KEY — a key the client chose to send (set in this
     process's environment by the client when it launches the server);
  2. the server's own: ANTHROPIC_API_KEY from the environment, or from a
     `.env` file next to this script (the environment wins).

Progress goes to stderr, one tagged line per step ([llm], [answer], [retry],
[ok], …) — clients may display it. stdout is reserved for MCP.

Run standalone:   .venv/bin/python mcp_server.py      (stdio transport)
"""
import json
import os
import re
import traceback
from pathlib import Path
from typing import Any

import anthropic
import anyio.to_thread
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel

import fillform as ff
import run_search as rs
from fillform import log

HERE = Path(__file__).resolve().parent
MODEL = "claude-opus-5-5"
MAX_ATTEMPTS = 3
MAX_TOKENS = 16_000
MAX_RESULTS_CAP = 100       # listings scraped at most per search (5 result pages)


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (KEY=value lines); existing env vars win."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


CLIENT_KEY_ENV = "INGATLAN_CLIENT_API_KEY"

_load_dotenv(HERE / ".env")
_client_key = os.environ.get(CLIENT_KEY_ENV, "").strip()
KEY_SOURCE = "client" if _client_key else "server"
_claude = anthropic.AsyncAnthropic(api_key=_client_key) if _client_key else anthropic.AsyncAnthropic()

mcp = MCPServer(
    name="ingatlan-search",
    instructions="Search flats/houses on ingatlan.com from a plain-language description.",
)


# ---------- prompt ----------------------------------------------------------

def _schema_doc() -> str:
    """Field reference generated from fillform's constants (stays in sync)."""
    groups = "\n".join(f"  - {g}: {opts}" for g, opts in ff.CHECKBOX_GROUPS.items())
    floors = ["semiBasement", "ground", "mezzanine", "first", "second", "third", "fourth",
              "fifth", "sixth", "seventh", "eight", "ninth", "tenth", "aboveTen"]
    return f"""\
Fields (omit a field, or set it to null, to leave it unset):

Main bar
  - listingType: one of {sorted(ff.LISTING_TYPES)}   ("eladó" = sale, "kiadó" = rent)
  - propertyType: one of {sorted(ff.PROPERTY_TYPES)}   (lakás = flat, ház = house, telek = plot)
  - location: a string or a list of strings, written the way ingatlan.com names places,
    e.g. "Budapest XI. kerület", "Budaörs", "Debrecen", "Sasad, Budapest XI. kerület"
  - priceFrom / priceTo: integers, MILLION HUF (for a sale) — for a rent this is
    thousand HUF per month
  - areaFrom / areaTo: integers, m²
  - roomsFrom / roomsTo: integers
  - wekerlePlusLoan, newlyBuilt: true / false

Detailed panel — checkbox groups: a list of the allowed values below,
or [] for "any" (mindegy)
{groups}

Detailed panel — other fields
  - floorFrom / floorTo: one of {floors}   (note the spelling "eight")
  - innerHeight: one of {sorted(ff.INNER_HEIGHT_VALUES)}   (high = 3 m or more)
  - {", ".join(ff.RADIO_FIELDS)}:
      true = must have it ("van"); "any" = don't care. There is NO "must not have"
      option: if the user wants to exclude a feature, leave the field unset and
      put a word in excludesKeyword instead.
  - euroPriceFrom / euroPriceTo: integers, THOUSAND EUR. Mutually exclusive with
    priceFrom/priceTo: only use them if the user gives the budget in euros.
  - containsKeyword / excludesKeyword: free text (Hungarian works best)
  - {", ".join(ff.BOOLEAN_FIELDS)}: true / false"""


SYSTEM_PROMPT = f"""\
You convert a description of the property someone is looking for into a JSON
search object for the Hungarian real-estate site ingatlan.com.

{_schema_doc()}

Rules:
  - Only set fields the description actually implies. Don't invent constraints.
  - Convert units yourself (e.g. "80 millió" -> priceTo 80, "under 300k EUR" ->
    euroPriceTo 300, "at least 3 rooms" -> roomsFrom 3).
  - Reply with the JSON object only: no prose, no code fences."""


# ---------- LLM + validation ------------------------------------------------

def _parse(text: str) -> tuple[dict | None, str]:
    """-> (complete validated dict, "") or (None, error message for the LLM)."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())   # tolerate fences
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        return None, "The reply contains no JSON object."
    try:
        obj = json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        return None, f"The reply is not valid JSON: {e}"
    if not isinstance(obj, dict):
        return None, "The JSON must be an object."
    data = {key: None for key in ff.ALL_KEYS} | obj          # omitted = unset
    try:
        ff.validate(data)
    except ValueError as e:
        return None, str(e)
    return data, ""


async def _ask_claude(messages: list[dict]) -> str:
    try:
        response = await _claude.beta.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=messages,
            output_config={"effort": "medium"},
            # On a safety decline, the API retries on a fallback model by itself.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.AuthenticationError:
        raise ToolError(f"The {KEY_SOURCE}'s Anthropic API key is invalid") from None
    except anthropic.RateLimitError:
        raise ToolError("Claude API rate limit reached, try again in a moment") from None
    except anthropic.APIStatusError as e:
        raise ToolError(f"Claude API error {e.status_code}: {e.message}") from None
    except anthropic.APIConnectionError:
        raise ToolError("The server cannot reach the Claude API") from None
    except TypeError as e:
        if "authentication" not in str(e):
            raise
        raise ToolError("The server has no Anthropic API key: put ANTHROPIC_API_KEY=... "
                        f"in {HERE / '.env'}") from None
    if response.stop_reason == "refusal":
        raise ToolError("Claude declined the request")
    return "".join(b.text for b in response.content if b.type == "text")


async def build_search(description: str) -> tuple[dict, int]:
    """Ask Claude for the search dict; feed validation errors back on failure."""
    messages = [{"role": "user", "content": f"What the user is looking for:\n\n{description}"}]
    error = ""
    log(f"[info] Using the {KEY_SOURCE}'s Anthropic API key")
    for attempt in range(1, MAX_ATTEMPTS + 1):
        log(f"[llm] Asking {MODEL} (attempt {attempt})")
        text = await _ask_claude(messages)
        log(f"[answer] {' '.join(text.split())}")
        data, error = _parse(text)
        if data is not None:
            return data, attempt
        log(f"[retry] Answer {attempt} invalid: {' '.join(error.split())}")
        messages += [
            {"role": "assistant", "content": text},
            {"role": "user", "content": f"That search object is invalid:\n{error}\n\n"
                                        "Reply with the corrected JSON object only."},
        ]
    raise ToolError(f"Could not build a valid search after {MAX_ATTEMPTS} attempts:\n{error}")


# ---------- tool ------------------------------------------------------------

class Listing(BaseModel):
    id: str | None
    url: str
    price: str | None               # as shown, e.g. "82,90 M Ft" or "250 000 Ft/hó"
    price_per_m2: str | None
    address: str | None
    area: str | None                # e.g. "48 m2"
    rooms: str | None               # e.g. "2 + 1 fél"
    details: dict[str, str]         # every label/value on the card (Hungarian labels)
    image: str | None
    labels: list[str]               # badges, e.g. "Videó elérhető"


class Screenshot(BaseModel):
    name: str                       # e.g. "Filled search form", "Results page"
    mime: str                       # "image/jpeg"
    data: str                       # base64


class SearchResult(BaseModel):
    search: dict[str, Any]          # the fields that were set (unset ones omitted)
    attempts: int                   # Claude calls needed to get a valid search
    results_url: str | None         # None on a dry run
    total_results: int | None       # as announced by the site ("26 találat")
    listings: list[Listing]         # the scraped listings (up to max_results)
    screenshots: list[Screenshot]   # only when requested


@mcp.tool()
async def search_flats(description: str, dry_run: bool = False, max_results: int = 20,
                       screenshots: bool = False) -> SearchResult:
    """Search ingatlan.com for properties matching a plain-language description.

    Args:
        description: what you are looking for, in any language
            (e.g. "3 rooms, renovated, Budapest XI, under 90M Ft, with a balcony").
        dry_run: only build and return the search object, don't open the browser.
        max_results: how many listings to scrape from the results (0-100; 0 = none).
        screenshots: also return JPEG screenshots of the filled form and the results page.
    """
    if not 0 <= max_results <= MAX_RESULTS_CAP:
        raise ToolError(f"max_results must be between 0 and {MAX_RESULTS_CAP}")
    data, attempts = await build_search(description)
    scraped: dict = {"url": None, "total": None, "listings": [], "screenshots": []}
    if not dry_run:
        try:
            # Camoufox's sync API must not run on the event loop's thread.
            scraped = await anyio.to_thread.run_sync(
                lambda: rs.run(data, max_results=max_results, screenshots=screenshots))
        except Exception as e:
            traceback.print_exc()          # full detail in the server's stderr
            raise ToolError(f"Browser search failed: {type(e).__name__}: "
                            f"{str(e).splitlines()[0] if str(e) else 'no details'}") from None
    return SearchResult(
        search={k: data[k] for k in sorted(data) if data[k] is not None},
        attempts=attempts,
        results_url=scraped["url"],
        total_results=scraped["total"],
        listings=[Listing(**item) for item in scraped["listings"]],
        screenshots=[Screenshot(**shot) for shot in scraped["screenshots"]],
    )


if __name__ == "__main__":
    mcp.run("stdio")

"""MCP client (command line): describe the flat you want, get an ingatlan.com search.

Launches mcp_server.py over stdio and calls its `search_flats` tool. The
server calls Claude with its own API key, so this client needs none —
unless you pass --use-my-key, which sends this client's ANTHROPIC_API_KEY
to the server (as INGATLAN_CLIENT_API_KEY in the server's environment).

    .venv/bin/python mcp_client.py "3 szobás felújított lakás a XI. kerületben 90M alatt, erkéllyel"
    .venv/bin/python mcp_client.py --dry-run "2 bedroom flat for rent in Budaörs"
    .venv/bin/python mcp_client.py --screenshots shots/ "..."
    ANTHROPIC_API_KEY=sk-ant-... .venv/bin/python mcp_client.py --use-my-key "..."
"""
import argparse
import asyncio
import base64
import json
import os
import re
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters

HERE = Path(__file__).resolve().parent


def save_screenshots(shots: list[dict], folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for i, shot in enumerate(shots, 1):
        path = folder / f"{i}-{re.sub(r'[^a-z0-9]+', '-', shot['name'].lower()).strip('-')}.jpg"
        path.write_bytes(base64.b64decode(shot["data"]))
        print(f"saved {path}", file=sys.stderr)


async def main(description: str, dry_run: bool, api_key: str | None,
               max_results: int, screenshots_dir: Path | None) -> int:
    # The SDK passes the server only a minimal environment (PATH, HOME, …),
    # so the server uses its own API key unless we explicitly send ours.
    env = {"INGATLAN_CLIENT_API_KEY": api_key} if api_key else None
    server = StdioServerParameters(command=sys.executable, args=[str(HERE / "mcp_server.py")],
                                   cwd=HERE, env=env)
    async with Client(server) as client:
        result = await client.call_tool(
            "search_flats",
            {"description": description, "dry_run": dry_run, "max_results": max_results,
             "screenshots": screenshots_dir is not None},
        )
    if result.is_error:
        message = "".join(getattr(c, "text", "") for c in result.content)
        print("Error: " + message.removeprefix("Error executing tool search_flats: "), file=sys.stderr)
        return 1
    payload = result.structured_content
    if payload is None:                       # server sent text only
        payload = json.loads("".join(getattr(c, "text", "") for c in result.content))
    shots = payload.pop("screenshots", [])
    if screenshots_dir and shots:
        save_screenshots(shots, screenshots_dir)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("description", nargs="+", help="what you are looking for")
    ap.add_argument("--dry-run", action="store_true", help="only build the search object")
    ap.add_argument("--max-results", type=int, default=20, help="listings to scrape (0-100, default 20)")
    ap.add_argument("--screenshots", metavar="DIR", type=Path,
                    help="ask for screenshots of the browser and save them (JPEG) into DIR")
    ap.add_argument("--use-my-key", action="store_true",
                    help="send this client's ANTHROPIC_API_KEY to the server instead of using the server's key")
    args = ap.parse_args()
    key = None
    if args.use_my_key:
        key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not key:
            ap.error("--use-my-key needs ANTHROPIC_API_KEY set in this shell")
    sys.exit(asyncio.run(main(" ".join(args.description), args.dry_run, key,
                              args.max_results, args.screenshots)))

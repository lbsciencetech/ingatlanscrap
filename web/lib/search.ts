// Server-side only (imported by the API route): MCP client that runs
// ../mcp_server.py and calls its search_flats tool. The MCP server calls
// Claude with the API key the user typed in the page (required).
import path from "node:path";
import readline from "node:readline";
import type { Readable } from "node:stream";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { getDefaultEnvironment, StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

import type { SearchEvent, SearchRequest, SearchResult } from "./events";

// The Python project lives one level above web/ (override with INGATLAN_ROOT).
const ROOT = process.env.INGATLAN_ROOT ?? path.resolve(process.cwd(), "..");
const PYTHON = process.env.INGATLAN_PYTHON ?? path.join(ROOT, ".venv", "bin", "python");
const TOOL_TIMEOUT_MS = 10 * 60_000; // Claude + a full browser run
// Each search runs a Python process + a browser (~400 MB): cap how many run at once.
const MAX_CONCURRENT = Math.max(1, Number(process.env.MAX_CONCURRENT_SEARCHES ?? 2) || 2);
let active = 0;
const waiting: Array<() => void> = [];

/** Wait for a free slot; resolves to a release function. */
async function acquireSlot(emit: (e: SearchEvent) => void, signal: AbortSignal): Promise<() => void> {
  if (active >= MAX_CONCURRENT) {
    emit({ type: "status", message: `Server busy: waiting for a free slot (${waiting.length + 1} in line)…` });
    await new Promise<void>((resolve, reject) => {
      const wake = () => { signal.removeEventListener("abort", onAbort); resolve(); };
      const onAbort = () => {
        const i = waiting.indexOf(wake);
        if (i >= 0) waiting.splice(i, 1);
        reject(new Error("cancelled while waiting"));
      };
      signal.addEventListener("abort", onAbort, { once: true });
      waiting.push(wake);
    });
  } else {
    active += 1;
  }
  let released = false;
  return () => {
    if (released) return;
    released = true;
    const next = waiting.shift();
    if (next) next();          // hand the slot over directly
    else active -= 1;
  };
}

// Give the server only a minimal environment (PATH, HOME, …) plus the user's
// key, so it never inherits another key from the web app by accident.
function serverEnv(apiKey: string): Record<string, string> {
  const env: Record<string, string> = { ...getDefaultEnvironment(), PYTHONUNBUFFERED: "1" };
  env.INGATLAN_CLIENT_API_KEY = apiKey;
  return env;
}

type Emit = (event: SearchEvent) => void;

function textOf(content: unknown): string {
  const blocks = Array.isArray(content) ? content : [content];
  return blocks
    .map((b) => (b && typeof b === "object" && (b as { type?: string }).type === "text"
      ? (b as { text: string }).text : ""))
    .join("");
}

/** Turn one tagged progress line from the server's stderr into an event. */
function toEvent(line: string): SearchEvent | null {
  const m = /^\[(\w+)\]\s*(.*)$/.exec(line);
  if (!m) return null;
  const [, tag, rest] = m;
  switch (tag) {
    case "llm": return { type: "status", message: rest };
    case "answer": return { type: "answer", text: rest };
    case "retry": return { type: "retry", message: rest };
    case "ok": case "warn": case "skip": case "info": return { type: "log", line: rest };
    default: return null;
  }
}

function pipeLines(stream: Readable | null, onLine: (line: string) => void) {
  if (!stream) return;
  readline.createInterface({ input: stream }).on("line", (line) => {
    const clean = line.trim();
    if (clean) onLine(clean);
  });
}

export async function runSearch(req: SearchRequest, emit: Emit, signal: AbortSignal): Promise<void> {
  let release: () => void;
  try {
    release = await acquireSlot(emit, signal);
  } catch {
    return; // cancelled while waiting
  }
  try {
    await runOne(req, emit, signal);
  } finally {
    release();
  }
}

async function runOne(req: SearchRequest, emit: Emit, signal: AbortSignal): Promise<void> {
  const transport = new StdioClientTransport({
    command: PYTHON,
    args: [path.join(ROOT, "mcp_server.py")],
    cwd: ROOT,
    stderr: "pipe",
    env: serverEnv(req.apiKey),
  });
  pipeLines(transport.stderr as Readable | null, (line) => {
    const event = toEvent(line);
    if (event) emit(event);
  });

  const client = new Client({ name: "ingatlan-search-web", version: "1.0.0" });

  const onAbort = () => void client.close();
  signal.addEventListener("abort", onAbort);
  try {
    emit({ type: "status", message: "Starting MCP server…" });
    await client.connect(transport);

    const result = await client.callTool(
      {
        name: "search_flats",
        arguments: {
          description: req.description,
          dry_run: req.dryRun,
          max_results: req.maxResults,
          screenshots: req.screenshots,
        },
      },
      undefined,
      { timeout: TOOL_TIMEOUT_MS, signal },
    );

    const text = textOf(result.content);
    if (result.isError) {
      emit({ type: "error", message: text.replace(/^Error executing tool search_flats: /, "") });
      return;
    }
    const payload = (result.structuredContent ?? JSON.parse(text)) as SearchResult;
    emit({ type: "result", result: payload });
  } catch (err) {
    const message = (err as Error).message.replace(/^(MCP error -?\d+: )+/, "");
    if (!signal.aborted) emit({ type: "error", message });
  } finally {
    signal.removeEventListener("abort", onAbort);
    await client.close().catch(() => {});
  }
}

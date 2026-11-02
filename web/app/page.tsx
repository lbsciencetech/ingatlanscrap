"use client";

import { useRef, useState } from "react";

import type { Listing, SearchEvent, SearchResult } from "@/lib/events";

const EXAMPLES = [
  "3 szobás felújított lakás a XI. kerületben 90 millió alatt, erkéllyel, lifttel",
  "2 bedroom flat for rent in Budaörs, max 300k HUF a month, with parking",
  "Family house near Debrecen, at least 120 m², garden, under 250k EUR",
];

// Human-readable labels for the search fields shown in the result card.
const LABELS: Record<string, string> = {
  listingType: "Listing", propertyType: "Type", location: "Location",
  priceFrom: "Price from (M Ft)", priceTo: "Price to (M Ft)",
  areaFrom: "Area from (m²)", areaTo: "Area to (m²)",
  roomsFrom: "Rooms from", roomsTo: "Rooms to",
  euroPriceFrom: "Price from (k €)", euroPriceTo: "Price to (k €)",
  floorFrom: "Floor from", floorTo: "Floor to", innerHeight: "Ceiling height",
  containsKeyword: "Must mention", excludesKeyword: "Must not mention",
};

function label(key: string): string {
  return LABELS[key] ?? key.replace(/([A-Z])/g, " $1").replace(/^./, (c) => c.toUpperCase());
}

function show(value: unknown): string {
  if (Array.isArray(value)) return value.length ? value.join(", ") : "any";
  if (value === true) return "yes";
  if (value === false) return "no";
  return String(value);
}

type Step = { kind: "status" | "retry" | "llm" | "log" | "error"; text: string; detail?: string };

function toStep(e: SearchEvent): Step | null {
  switch (e.type) {
    case "status": return { kind: "status", text: e.message };
    case "answer": return { kind: "llm", text: "Claude answered", detail: e.text };
    case "retry": return { kind: "retry", text: `${e.message} — asking again with the errors` };
    case "log": return { kind: "log", text: e.line };
    case "error": return { kind: "error", text: e.message };
    default: return null;
  }
}

const MAX_RESULTS_OPTIONS = [10, 20, 50, 100];

/** "48 m2" -> "48 m²" (the site renders the 2 as <sup>). */
function m2(text: string | null): string | null {
  return text ? text.replace(/m2\b/g, "m²") : text;
}

function ListingCard({ item }: { item: Listing }) {
  const extras = Object.entries(item.details).filter(([k]) => k !== "Alapterület" && k !== "Szobák");
  return (
    <a className="listing" href={item.url} target="_blank" rel="noreferrer">
      <div className="photo">
        {item.image ? (
          // eslint-disable-next-line @next/next/no-img-element -- remote CDN thumbnail
          <img src={item.image} alt="" loading="lazy" referrerPolicy="no-referrer" />
        ) : (
          <span className="muted small">No photo</span>
        )}
        {item.labels.length > 0 && <span className="badge">{item.labels[0]}</span>}
      </div>
      <div className="info">
        <div className="price">{item.price ?? "Price on request"}</div>
        {item.price_per_m2 && <div className="muted small ppm">{m2(item.price_per_m2)}</div>}
        <div className="addr">{item.address}</div>
        <div className="facts">
          {item.area && <span><b>{m2(item.area)}</b></span>}
          {item.rooms && <span><b>{item.rooms}</b> rooms</span>}
          {extras.map(([k, v]) => (
            <span key={k} className="muted">{k}: {m2(v)}</span>
          ))}
        </div>
      </div>
    </a>
  );
}

export default function Page() {
  const [description, setDescription] = useState("");
  const [dryRun, setDryRun] = useState(false);
  const [screenshots, setScreenshots] = useState(false);
  const [zoomed, setZoomed] = useState<number | null>(null);
  const [maxResults, setMaxResults] = useState(20);
  // Kept in memory only (never stored); empty = the MCP server uses its own key.
  const [apiKey, setApiKey] = useState("");
  const [running, setRunning] = useState(false);
  const [steps, setSteps] = useState<Step[]>([]);
  const [result, setResult] = useState<SearchResult | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  async function search(e: React.FormEvent) {
    e.preventDefault();
    if (!description.trim() || running) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setRunning(true);
    setSteps([]);
    setResult(null);
    setZoomed(null);

    try {
      const res = await fetch("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ description, dryRun, screenshots, maxResults, apiKey: apiKey.trim() || undefined }),
        signal: controller.signal,
      });
      if (!res.ok || !res.body) {
        const err = await res.json().catch(() => ({ error: res.statusText }));
        setSteps([{ kind: "error", text: err.error ?? "Request failed" }]);
        return;
      }
      const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
      let buffer = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += value;
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.trim()) continue;
          const event = JSON.parse(line) as SearchEvent;
          if (event.type === "result") setResult(event.result);
          const step = toStep(event);
          if (step) setSteps((s) => [...s, step]);
        }
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setSteps((s) => [...s, { kind: "error", text: (err as Error).message }]);
      } else {
        setSteps((s) => [...s, { kind: "error", text: "Cancelled" }]);
      }
    } finally {
      setRunning(false);
      abortRef.current = null;
    }
  }

  return (
    <main className="wrap">
      <header>
        <h1>Flat finder</h1>
        <p className="sub">
          Describe what you&apos;re looking for. An MCP server asks Claude to turn it into an
          ingatlan.com search, checks it, then runs it in a real browser.
        </p>
      </header>

      <form onSubmit={search} className="card">
        <label htmlFor="desc" className="visually-hidden">Description</label>
        <textarea
          id="desc"
          rows={4}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="e.g. 3 szobás felújított lakás a XI. kerületben 90 millió alatt, erkéllyel"
          disabled={running}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) e.currentTarget.form?.requestSubmit();
          }}
        />
        <div className="examples">
          {EXAMPLES.map((ex) => (
            <button key={ex} type="button" className="chip" disabled={running}
                    onClick={() => setDescription(ex)}>
              {ex}
            </button>
          ))}
        </div>
        <div className="key">
          <label htmlFor="apikey">Your Anthropic API key <span className="muted">(optional)</span></label>
          <input
            id="apikey"
            type="password"
            autoComplete="off"
            spellCheck={false}
            placeholder="Leave empty to use the server's key"
            value={apiKey}
            disabled={running}
            onChange={(e) => setApiKey(e.target.value)}
          />
        </div>
        <div className="row">
          <label className="check">
            <input type="checkbox" checked={dryRun} disabled={running}
                   onChange={(e) => setDryRun(e.target.checked)} />
            Only build the search (no browser)
          </label>
          <label className="check">
            <input type="checkbox" checked={screenshots} disabled={running || dryRun}
                   onChange={(e) => setScreenshots(e.target.checked)} />
            Include screenshots
          </label>
          <label className="check">
            Listings
            <select value={maxResults} disabled={running || dryRun}
                    onChange={(e) => setMaxResults(Number(e.target.value))}>
              {MAX_RESULTS_OPTIONS.map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
          <span className="spacer" />
          {running ? (
            <button type="button" className="btn secondary" onClick={() => abortRef.current?.abort()}>
              Cancel
            </button>
          ) : (
            <button type="submit" className="btn" disabled={!description.trim()}>
              Search
            </button>
          )}
        </div>
      </form>

      {steps.length > 0 && (
        <section className="card" aria-live="polite">
          <h2>Progress {running && <span className="spinner" aria-label="running" />}</h2>
          <ol className="steps">
            {steps.map((s, i) => (
              <li key={i} className={`step ${s.kind}`}>
                <span>{s.text}</span>
                {s.detail && (
                  <details>
                    <summary>Show answer</summary>
                    <pre>{s.detail}</pre>
                  </details>
                )}
              </li>
            ))}
          </ol>
        </section>
      )}

      {result && (
        <section className="card result">
          <h2>Search</h2>
          {result.results_url ? (
            <a className="btn" href={result.results_url} target="_blank" rel="noreferrer">
              Open results on ingatlan.com ↗
            </a>
          ) : (
            <p className="muted">Dry run: the browser was not started.</p>
          )}
          <dl className="fields">
            {Object.entries(result.search).map(([k, v]) => (
              <div key={k}>
                <dt>{label(k)}</dt>
                <dd>{show(v)}</dd>
              </div>
            ))}
          </dl>
          <p className="muted small">
            Built in {result.attempts} Claude call{result.attempts > 1 ? "s" : ""}.
          </p>
        </section>
      )}

      {result && result.screenshots.length > 0 && (
        <section className="card">
          <h2>Screenshots <span className="muted">— click to enlarge</span></h2>
          <div className="shots">
            {result.screenshots.map((shot, i) => (
              <figure key={i} className={zoomed === i ? "shot zoomed" : "shot"}>
                <button type="button" onClick={() => setZoomed(zoomed === i ? null : i)}
                        aria-label={`${zoomed === i ? "Shrink" : "Enlarge"} ${shot.name}`}>
                  {/* eslint-disable-next-line @next/next/no-img-element -- inline base64 */}
                  <img src={`data:${shot.mime};base64,${shot.data}`} alt={shot.name} />
                </button>
                <figcaption className="muted small">{shot.name}</figcaption>
              </figure>
            ))}
          </div>
        </section>
      )}

      {result?.results_url && (
        <section className="card">
          <h2>
            {result.listings.length === 0
              ? "No listings found"
              : `${result.listings.length} listing${result.listings.length > 1 ? "s" : ""}`}
            {result.total_results !== null && result.total_results > result.listings.length && (
              <span className="muted"> of {result.total_results} — see all on ingatlan.com</span>
            )}
          </h2>
          <div className="listings">
            {result.listings.map((item) => <ListingCard key={item.url} item={item} />)}
          </div>
        </section>
      )}
    </main>
  );
}

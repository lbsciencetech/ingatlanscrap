"use client";

import { useRef, useState } from "react";

import type { Listing, SearchEvent, SearchResult } from "@/lib/events";

const EXAMPLES = [
  { short: "3 rooms, XI. district, < 90 M Ft", text: "3 szobás felújított lakás a XI. kerületben 90 millió alatt, erkéllyel, lifttel" },
  { short: "Rent in Budaörs, parking", text: "2 bedroom flat for rent in Budaörs, max 300k HUF a month, with parking" },
  { short: "House near Debrecen, garden", text: "Family house near Debrecen, at least 120 m², garden, under 250k EUR" },
];

const MAX_RESULTS_OPTIONS = [10, 20, 50, 100];

// ───────────────────────── search criteria → readable chips ─────────────────────────

const NAMES: Record<string, string> = {
  listingType: "Listing", propertyType: "Type", location: "Location",
  price: "Price", euroPrice: "Price", area: "Area", rooms: "Rooms", floor: "Floor",
  innerHeight: "Ceiling", containsKeyword: "Mentions", excludesKeyword: "Excludes",
  propertySubtype: "Building", yearOfConstruction: "Built", heatingType: "Heating",
  comfortLevel: "Comfort", atticType: "Attic", bathroomToiletSeparation: "Bathroom/WC",
};
const UNITS: Record<string, string> = { price: " M Ft", euroPrice: " k €", area: " m²" };

function humanize(s: string): string {
  return s
    .replace(/^(has|is)(?=[A-Z])/, "")
    .replace(/([a-z])([A-Z0-9])/g, "$1 $2")
    .toLowerCase()
    .replace(/^./, (c) => c.toUpperCase());
}

function isEmpty(v: unknown): boolean {
  return v === null || v === undefined || v === false || v === "any" || (Array.isArray(v) && v.length === 0);
}

/** Only what Claude actually set: ranges merged ("40–90 M Ft"), defaults dropped. */
function criteria(search: Record<string, unknown>): { name: string; value: string }[] {
  const out: { name: string; value: string }[] = [];
  const done = new Set<string>();
  for (const [key, value] of Object.entries(search)) {
    if (done.has(key)) continue;
    const range = key.match(/^(.*)(From|To)$/);
    if (range) {
      const base = range[1];
      const from = search[`${base}From`], to = search[`${base}To`];
      done.add(`${base}From`).add(`${base}To`);
      if (isEmpty(from) && isEmpty(to)) continue;
      const fmt = (v: unknown) => (typeof v === "string" ? humanize(v) : String(v));
      const unit = UNITS[base] ?? "";
      const value =
        !isEmpty(from) && !isEmpty(to) ? `${fmt(from)}–${fmt(to)}${unit}`
        : !isEmpty(from) ? `from ${fmt(from)}${unit}` : `up to ${fmt(to)}${unit}`;
      out.push({ name: NAMES[base] ?? humanize(base), value });
      continue;
    }
    if (isEmpty(value)) continue;
    if (value === true) {
      out.push({ name: "", value: humanize(key) });
    } else {
      const v = Array.isArray(value) ? value.map((x) => humanize(String(x))).join(", ")
        : key === "location" || key.endsWith("Keyword") ? String(value) : humanize(String(value));
      out.push({ name: NAMES[key] ?? humanize(key), value: v });
    }
  }
  return out;
}

// ───────────────────────── live progress (mapped onto the 3 stages) ─────────────────────────

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

type StageState = "todo" | "active" | "done" | "error" | "skipped";
type Progress = { states: StageState[]; notes: string[] };

const STAGES = ["Claude builds the search", "Browser runs it", "Listings come back"];

function progress(steps: Step[], result: SearchResult | null, running: boolean, dryRun: boolean): Progress {
  let stage = 0;
  let failed = false;
  let attempts = 0;
  const notes = ["Waiting…", "", ""];
  for (const s of steps) {
    if (s.kind === "status") {
      if (s.text.startsWith("Asking")) attempts += 1;
      notes[0] = s.text.startsWith("Asking") ? `Writing the search (attempt ${attempts})` : s.text;
    } else if (s.kind === "llm") {
      notes[0] = "Answer checked against the form's rules";
      if (!dryRun) { stage = 1; notes[1] = "Opening ingatlan.com…"; }
    } else if (s.kind === "retry") {
      stage = 0;
      notes[0] = "Answer rejected by the validator — asking again";
    } else if (s.kind === "log") {
      if (/^Using the/.test(s.text)) notes[0] = s.text;
      else if (/^(results:|page \d|scraped)/.test(s.text)) {
        stage = 2;
        notes[1] = "Search submitted";
        notes[2] = s.text.startsWith("results:") ? "Reading the results page…" : s.text.replace(/^page/, "Page");
      } else if (!/^screenshot/.test(s.text)) {
        stage = Math.max(stage, 1);
        notes[1] = s.text.replace(/^location:/, "Location picked:").replace(/^cookies accepted/, "Cookie banner accepted");
      }
    } else if (s.kind === "error") {
      failed = true;
    }
  }
  const states: StageState[] = STAGES.map((_, i) => {
    if (result) return dryRun && i > 0 ? "skipped" : "done";
    if (i < stage) return "done";
    if (i === stage) return failed ? "error" : running ? "active" : "todo";
    return dryRun && i > 0 ? "skipped" : "todo";
  });
  if (result) {
    notes[0] = `Built in ${result.attempts} Claude call${result.attempts > 1 ? "s" : ""}`;
    if (!dryRun) {
      notes[1] = "Form filled and submitted";
      notes[2] = `${result.listings.length} listing${result.listings.length === 1 ? "" : "s"} collected`;
    } else {
      notes[1] = notes[2] = "Skipped (build only)";
    }
  } else if (dryRun) {
    notes[1] = notes[2] = "Skipped (build only)";
  }
  return { states, notes };
}

// ───────────────────────── small pieces ─────────────────────────

function Icon({ name }: { name: "chat" | "spark" | "browser" | "list" | "lock" | "shield" | "camera" }) {
  const paths: Record<string, React.ReactNode> = {
    chat: <path d="M4 5h16v11H9l-5 4z" />,
    spark: <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z" />,
    browser: <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M3 9h18M7 6.5h.01M10 6.5h.01" /></>,
    list: <path d="M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01" />,
    lock: <><rect x="5" y="11" width="14" height="9" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3" /></>,
    shield: <path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z" />,
    camera: <><path d="M4 8h3l2-3h6l2 3h3v11H4z" /><circle cx="12" cy="13" r="3.5" /></>,
  };
  return (
    <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {paths[name]}
    </svg>
  );
}

/** "48 m2" -> "48 m²" (the site renders the 2 as <sup>). */
function m2(text: string | null): string | null {
  return text ? text.replace(/m2\b/g, "m²") : text;
}

// Extra facts on the listing cards come with Hungarian labels.
const DETAIL_NAMES: Record<string, string> = {
  "Erkély": "Balcony", "Terasz": "Terrace", "Telekterület": "Plot", "Kert": "Garden",
};

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
        <div className="price-row">
          <span className="price">{item.price ?? "Price on request"}</span>
          {item.price_per_m2 && <span className="ppm">{m2(item.price_per_m2)}</span>}
        </div>
        <div className="addr">{item.address}</div>
        <div className="facts">
          {item.area && <span className="fact">{m2(item.area)}</span>}
          {item.rooms && <span className="fact">{item.rooms} rooms</span>}
          {extras.map(([k, v]) => (
            <span key={k} className="fact subtle" title={k}>{DETAIL_NAMES[k] ?? k} {m2(v)}</span>
          ))}
        </div>
      </div>
    </a>
  );
}

function HowItWorks() {
  const steps = [
    { icon: "chat" as const, title: "You describe it", text: "Write what you want in plain words — Hungarian, English or French. Budget, district, rooms, balcony, lift…" },
    { icon: "spark" as const, title: "Claude builds the search", text: "Claude translates your words into the exact fields of ingatlan.com's search form. A validator checks every value; if one is wrong, Claude gets the errors and fixes it (up to 3 tries)." },
    { icon: "browser" as const, title: "A real browser runs it", text: "A stealth Firefox (Camoufox) opens ingatlan.com, fills the form field by field like a person would and submits it — the same search you could do by hand." },
    { icon: "list" as const, title: "Listings come back", text: "The results pages are read and the matching listings are shown here, with a link to each ad and to the full search on ingatlan.com." },
  ];
  return (
    <section id="how" className="how" aria-labelledby="how-title">
      <p className="eyebrow">How it works</p>
      <h2 id="how-title" className="section-title">From a sentence to real listings, in four steps</h2>
      <ol className="how-steps">
        {steps.map((s, i) => (
          <li key={s.title} className="how-step">
            <div className="how-icon"><Icon name={s.icon} /><span className="how-num">{i + 1}</span></div>
            <h3>{s.title}</h3>
            <p>{s.text}</p>
          </li>
        ))}
      </ol>
      <div className="notes">
        <div className="note">
          <Icon name="shield" />
          <div>
            <b>Why a browser, not an API?</b> ingatlan.com has no public search API. Filling the real form
            means the results are exactly what the site shows — nothing guessed.
          </div>
        </div>
        <div className="note">
          <Icon name="lock" />
          <div>
            <b>Your API key stays with you.</b> Each search needs your own Anthropic key: it is sent with
            that one search only and never stored.
          </div>
        </div>
        <div className="note">
          <Icon name="camera" />
          <div>
            <b>Want proof?</b> Tick <i>Screenshots</i> to get pictures of the filled form and of the results
            page, taken by the browser during the search.
          </div>
        </div>
      </div>
      <p className="tech">
        Under the hood: this page talks to an <abbr title="Model Context Protocol">MCP</abbr> server
        (tool <code>search_flats</code>) that calls Claude, validates the answer, then drives Camoufox.
      </p>
    </section>
  );
}

// ───────────────────────── page ─────────────────────────

export default function Page() {
  const [description, setDescription] = useState("");
  const [dryRun, setDryRun] = useState(false);
  const [screenshots, setScreenshots] = useState(false);
  const [zoomed, setZoomed] = useState<number | null>(null);
  const [maxResults, setMaxResults] = useState(20);
  // Required. Kept in memory only (never stored), sent with each search.
  const [apiKey, setApiKey] = useState("");
  const [running, setRunning] = useState(false);
  const [ranDryRun, setRanDryRun] = useState(false);
  const [steps, setSteps] = useState<Step[]>([]);
  const [result, setResult] = useState<SearchResult | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const resultsRef = useRef<HTMLDivElement | null>(null);

  async function search(e: React.FormEvent) {
    e.preventDefault();
    if (!description.trim() || !apiKey.trim() || running) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setRunning(true);
    setRanDryRun(dryRun);
    setSteps([]);
    setResult(null);
    setZoomed(null);
    requestAnimationFrame(() => resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));

    try {
      const res = await fetch("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ description, dryRun, screenshots, maxResults, apiKey: apiKey.trim() }),
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
      const aborted = (err as Error).name === "AbortError";
      setSteps((s) => [...s, { kind: "error", text: aborted ? "Cancelled" : (err as Error).message }]);
    } finally {
      setRunning(false);
      abortRef.current = null;
    }
  }

  const started = running || steps.length > 0 || result !== null;
  const prog = progress(steps, result, running, ranDryRun);
  const errors = steps.filter((s) => s.kind === "error");
  const chips = result ? criteria(result.search) : [];

  return (
    <>
      <nav className="topbar">
        <div className="topbar-inner">
          <a href="#" className="brand">
            <span className="logo" aria-hidden="true">
              <svg viewBox="0 0 24 24"><path d="M3 11.5L12 4l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z" /></svg>
            </span>
            Flat finder
          </a>
          <a href="#how" className="toplink">How it works</a>
        </div>
      </nav>

      <main className="wrap">
        <header className="hero">
          <p className="eyebrow">Search ingatlan.com in plain words</p>
          <h1>Describe the flat.<br /><em>We&apos;ll do the searching.</em></h1>
          <p className="lede">
            Tell us what you&apos;re looking for. Claude turns it into a precise ingatlan.com search,
            a real browser runs it, and the matching listings land right here.
          </p>
        </header>

        <form onSubmit={search} className="composer">
          <label htmlFor="desc" className="visually-hidden">What are you looking for?</label>
          <textarea
            id="desc"
            rows={3}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="e.g. A renovated 3-room flat in the XI. district under 90 million, with a balcony and a lift"
            disabled={running}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) e.currentTarget.form?.requestSubmit();
            }}
          />
          <div className="examples">
            <span className="muted small-label">Try</span>
            {EXAMPLES.map((ex) => (
              <button key={ex.text} type="button" className="chip" disabled={running}
                      title={ex.text} onClick={() => setDescription(ex.text)}>
                {ex.short}
              </button>
            ))}
          </div>

          <div className="composer-bar">
            <div className="options">
              <div className="segmented" role="radiogroup" aria-label="Mode">
                <button type="button" role="radio" aria-checked={!dryRun} disabled={running}
                        className={!dryRun ? "on" : ""} onClick={() => setDryRun(false)}>
                  Find listings
                </button>
                <button type="button" role="radio" aria-checked={dryRun} disabled={running}
                        className={dryRun ? "on" : ""} onClick={() => setDryRun(true)}
                        title="Only ask Claude to build the search; the browser is not started">
                  Build search only
                </button>
              </div>
              <label className="opt">
                <span>Show</span>
                <select value={maxResults} disabled={running || dryRun}
                        onChange={(e) => setMaxResults(Number(e.target.value))}>
                  {MAX_RESULTS_OPTIONS.map((n) => <option key={n} value={n}>{n}</option>)}
                </select>
                <span>listings</span>
              </label>
              <label className="opt switch">
                <input type="checkbox" checked={screenshots} disabled={running || dryRun}
                       onChange={(e) => setScreenshots(e.target.checked)} />
                <span className="track" aria-hidden="true" />
                Screenshots
              </label>
            </div>
            {running ? (
              <button type="button" className="btn ghost" onClick={() => abortRef.current?.abort()}>
                Cancel
              </button>
            ) : (
              <button type="submit" className="btn" disabled={!description.trim() || !apiKey.trim()}
                      title={!apiKey.trim() ? "Enter your Anthropic API key first" : undefined}>
                Search <span aria-hidden="true">→</span>
              </button>
            )}
          </div>

          <div className="keybox">
            <label htmlFor="apikey" className="keylabel"><Icon name="lock" /> Anthropic API key <span className="req">required</span></label>
            <div className="keyrow">
              <input
                id="apikey"
                type="password"
                autoComplete="off"
                spellCheck={false}
                required
                placeholder="sk-ant-…"
                value={apiKey}
                disabled={running}
                onChange={(e) => setApiKey(e.target.value)}
              />
              <p className="muted small">
                Sent with each search only, never stored. Get one at{" "}
                <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noreferrer">console.anthropic.com</a>.
              </p>
            </div>
          </div>
        </form>

        <div ref={resultsRef} className="results-anchor" />

        {started && (
          <section className="panel" aria-live="polite" aria-label="Progress">
            <ol className="pipeline">
              {STAGES.map((title, i) => (
                <li key={title} className={`stage ${prog.states[i]}`}>
                  <span className="dot" aria-hidden="true">
                    {prog.states[i] === "done" ? "✓" : prog.states[i] === "error" ? "!" : i + 1}
                  </span>
                  <div>
                    <div className="stage-title">{title}</div>
                    <div className="stage-note">{prog.notes[i]}</div>
                  </div>
                </li>
              ))}
            </ol>
            {errors.length > 0 && (
              <div className="alert" role="alert">{errors[errors.length - 1].text}</div>
            )}
            {steps.length > 0 && (
              <details className="log">
                <summary>Details ({steps.length} steps)</summary>
                <ol>
                  {steps.map((s, i) => (
                    <li key={i} className={`logline ${s.kind}`}>
                      <span>{s.text}</span>
                      {s.detail && (
                        <details>
                          <summary>Claude&apos;s answer</summary>
                          <pre>{s.detail}</pre>
                        </details>
                      )}
                    </li>
                  ))}
                </ol>
              </details>
            )}
          </section>
        )}

        {result && (
          <section className="panel understood">
            <div className="understood-head">
              <div>
                <p className="eyebrow">What Claude understood</p>
                <h2 className="section-title small-title">Your search on ingatlan.com</h2>
              </div>
              {result.results_url && (
                <a className="btn outline" href={result.results_url} target="_blank" rel="noreferrer">
                  Open on ingatlan.com ↗
                </a>
              )}
            </div>
            <ul className="criteria">
              {chips.map((c, i) => (
                <li key={i}>{c.name && <span className="cname">{c.name}</span>}{c.value}</li>
              ))}
            </ul>
            {!result.results_url && (
              <p className="muted small">Build only: the browser was not started. Switch to <i>Find listings</i> to run it.</p>
            )}
          </section>
        )}

        {result && result.screenshots.length > 0 && (
          <section className="panel">
            <h2 className="panel-title">Screenshots <span className="muted">· click to enlarge</span></h2>
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
          <section className="listings-section">
            <div className="listings-head">
              <h2 className="section-title">
                {result.listings.length === 0
                  ? "No listings match"
                  : `${result.listings.length} listing${result.listings.length > 1 ? "s" : ""}`}
              </h2>
              {result.total_results !== null && result.total_results > result.listings.length && (
                <a className="muted" href={result.results_url} target="_blank" rel="noreferrer">
                  of {result.total_results} on ingatlan.com — see all ↗
                </a>
              )}
            </div>
            {result.listings.length === 0 ? (
              <p className="muted">Try a wider budget, area or location.</p>
            ) : (
              <div className="listings">
                {result.listings.map((item) => <ListingCard key={item.url} item={item} />)}
              </div>
            )}
          </section>
        )}

        <HowItWorks />
      </main>

      <footer className="footer">
        Flat finder is not affiliated with ingatlan.com. Listings belong to their advertisers.
      </footer>
    </>
  );
}

// Events streamed from /api/search to the page (one JSON object per line).

export type Listing = {
  id: string | null;
  url: string;
  price: string | null;          // as shown, e.g. "82,90 M Ft"
  price_per_m2: string | null;
  address: string | null;
  area: string | null;           // e.g. "48 m2"
  rooms: string | null;          // e.g. "2 + 1 fél"
  details: Record<string, string>;
  image: string | null;
  labels: string[];
};

export type Screenshot = {
  name: string;   // e.g. "Filled search form", "Results page"
  mime: string;   // "image/jpeg"
  data: string;   // base64
};

export type SearchResult = {
  search: Record<string, unknown>;
  attempts: number;
  results_url: string | null;
  total_results: number | null;
  listings: Listing[];
  screenshots: Screenshot[];
};

export type SearchEvent =
  | { type: "status"; message: string }          // client or server step
  | { type: "answer"; text: string }             // Claude's raw answer (server side)
  | { type: "retry"; message: string }           // answer failed validation
  | { type: "log"; line: string }                // browser progress
  | { type: "result"; result: SearchResult }
  | { type: "error"; message: string };

export type SearchRequest = {
  description: string;
  dryRun: boolean;
  screenshots: boolean; // ask the server for browser screenshots
  maxResults: number; // listings to scrape, 0-100
  apiKey?: string; // optional: the user's own Anthropic key, forwarded to the MCP server
};

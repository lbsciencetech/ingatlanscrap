import type { SearchEvent, SearchRequest } from "@/lib/events";
import { runSearch } from "@/lib/search";

export const runtime = "nodejs"; // spawns a child process
export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  let body: SearchRequest;
  try {
    body = (await request.json()) as SearchRequest;
  } catch {
    return Response.json({ error: "invalid JSON body" }, { status: 400 });
  }
  const description = typeof body.description === "string" ? body.description.trim() : "";
  if (!description) {
    return Response.json({ error: "description is required" }, { status: 400 });
  }
  if (description.length > 4000) {
    return Response.json({ error: "description is too long" }, { status: 400 });
  }
  const maxResults = body.maxResults === undefined ? 20 : Number(body.maxResults);
  if (!Number.isInteger(maxResults) || maxResults < 0 || maxResults > 100) {
    return Response.json({ error: "maxResults must be an integer between 0 and 100" }, { status: 400 });
  }
  const apiKey = typeof body.apiKey === "string" ? body.apiKey.trim() : "";
  if (apiKey.length > 300 || /\s/.test(apiKey)) {
    return Response.json({ error: "invalid API key format" }, { status: 400 });
  }

  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      const emit = (event: SearchEvent) => {
        try {
          controller.enqueue(encoder.encode(JSON.stringify(event) + "\n"));
        } catch {
          // stream already closed (client went away)
        }
      };
      await runSearch(
        {
          description,
          dryRun: Boolean(body.dryRun),
          screenshots: Boolean(body.screenshots),
          maxResults,
          apiKey: apiKey || undefined,
        },
        emit,
        request.signal, // closing the tab kills the Python server and its browser
      );
      try {
        controller.close();
      } catch {
        // already closed
      }
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "application/x-ndjson; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}

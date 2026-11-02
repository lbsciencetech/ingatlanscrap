// HTTP Basic auth in front of the whole app, enabled when APP_PASSWORD is set
// (production). Without it (local dev) every request passes through.
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

function safeEqual(a: string, b: string): boolean {
  // Constant-time comparison so the password can't be guessed by timing.
  const len = Math.max(a.length, b.length);
  let diff = a.length ^ b.length;
  for (let i = 0; i < len; i++) diff |= (a.charCodeAt(i) || 0) ^ (b.charCodeAt(i) || 0);
  return diff === 0;
}

export function proxy(request: NextRequest) {
  const password = process.env.APP_PASSWORD;
  if (!password) return NextResponse.next();
  const user = process.env.APP_USER || "admin";

  const header = request.headers.get("authorization") ?? "";
  if (header.startsWith("Basic ")) {
    const decoded = atob(header.slice(6));
    const sep = decoded.indexOf(":");
    if (sep >= 0 && safeEqual(decoded.slice(0, sep), user) && safeEqual(decoded.slice(sep + 1), password)) {
      return NextResponse.next();
    }
  }
  return new NextResponse("Authentication required", {
    status: 401,
    headers: { "WWW-Authenticate": 'Basic realm="Flat finder", charset="UTF-8"' },
  });
}

export const config = {
  // Everything except Next's static build assets (not sensitive).
  matcher: ["/((?!_next/static|_next/image).*)"],
};

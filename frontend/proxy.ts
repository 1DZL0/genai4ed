import { NextResponse, type NextRequest } from "next/server";
import { GATE_COOKIE, gateToken } from "@/lib/gate";

// Everything, pages and /api alike, waits behind one site password while the
// prototype is shown privately. No SITE_PASSWORD means the site is open.
export async function proxy(request: NextRequest) {
  const password = process.env.SITE_PASSWORD;
  const { pathname } = request.nextUrl;
  if (!password || pathname.startsWith("/gate")) return NextResponse.next();
  if (request.cookies.get(GATE_COOKIE)?.value === (await gateToken(password))) {
    return NextResponse.next();
  }
  if (pathname.startsWith("/api/"))
    return new NextResponse(null, { status: 401 });
  return NextResponse.redirect(new URL("/gate", request.url));
}

export const config = { matcher: ["/((?!_next/|favicon.ico).*)"] };

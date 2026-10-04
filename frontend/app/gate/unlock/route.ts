import { NextResponse } from "next/server";
import { GATE_COOKIE, gateToken } from "@/lib/gate";

const MONTH = 60 * 60 * 24 * 30;

/** The gate form posts here. Right password: a cookie for a month, then the home page. */
export async function POST(request: Request) {
  const password = process.env.SITE_PASSWORD ?? "";
  const given = String((await request.formData()).get("password") ?? "");
  if (!password || given !== password) {
    return new NextResponse(null, {
      status: 303,
      headers: { Location: "/gate?wrong=1" },
    });
  }
  const response = new NextResponse(null, {
    status: 303,
    headers: { Location: "/" },
  });
  response.cookies.set(GATE_COOKIE, await gateToken(password), {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    maxAge: MONTH,
  });
  return response;
}

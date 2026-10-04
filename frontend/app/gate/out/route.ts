import { NextResponse } from "next/server";
import { GATE_COOKIE } from "@/lib/gate";

/** "Sign out of everything" ends here: forget the site password and show the gate again. */
export async function GET() {
  const where = process.env.SITE_PASSWORD ? "/gate" : "/";
  const response = new NextResponse(null, {
    status: 303,
    headers: { Location: where },
  });
  response.cookies.delete(GATE_COOKIE);
  return response;
}

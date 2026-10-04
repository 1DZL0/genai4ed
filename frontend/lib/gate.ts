/** One password for the whole site while it is shown privately. */

export const GATE_COOKIE = "genai4ed_gate";

/** What the cookie holds once the password has been entered: a hash, not the password. */
export async function gateToken(password: string): Promise<string> {
  const bytes = new TextEncoder().encode(`genai4ed:${password}`);
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(hash), (b) =>
    b.toString(16).padStart(2, "0"),
  ).join("");
}

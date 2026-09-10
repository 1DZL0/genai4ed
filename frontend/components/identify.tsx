import Link from "next/link";
import { Panel } from "@/components/ui";

/** Shown when the browser has no pseudonym. Better than a silent redirect:
 *  it explains itself and keeps the URL the person was trying to reach. */
export function NotIdentified() {
  return (
    <main className="mx-auto w-full max-w-md px-4 py-16">
      <Panel title="Who is using this browser?">
        <p className="text-sm text-muted">
          This prototype needs to know which pseudonym to act as before it can show you
          anything.
        </p>
        <Link
          href="/"
          className="mt-4 inline-block rounded bg-accent px-3 py-2 text-sm font-medium text-white hover:bg-accent-hover"
        >
          Choose
        </Link>
      </Panel>
    </main>
  );
}

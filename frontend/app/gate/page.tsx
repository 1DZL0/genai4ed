import { Wordmark } from "@/components/app-header";
import { inputClass } from "@/components/auth-layout";
import { Button, ErrorNote } from "@/components/ui";

/** The one door into the site while it is shown privately. */
export default async function GatePage({
  searchParams,
}: {
  searchParams: Promise<{ wrong?: string }>;
}) {
  const { wrong } = await searchParams;
  return (
    <div className="flex min-h-full flex-1 flex-col">
      <header className="mx-auto flex h-14 w-full max-w-6xl items-center px-4 sm:px-6">
        <Wordmark />
      </header>
      <main className="flex flex-1 items-start justify-center px-4 pt-10 pb-16 sm:pt-20">
        <form
          method="post"
          action="/gate/unlock"
          className="w-full max-w-md rounded-[var(--radius-sheet)] border border-rule bg-sheet p-6 sm:p-8"
        >
          <h1 className="font-serif text-xl font-semibold text-ink">
            A private prototype.
          </h1>
          <p className="mt-1.5 mb-6 text-sm text-pencil">
            Enter the password you were given.
          </p>
          <label className="block text-sm font-semibold text-ink">
            Password
            <input
              name="password"
              type="password"
              required
              autoFocus
              className={inputClass}
            />
          </label>
          {wrong && (
            <div className="mt-3">
              <ErrorNote>That password isn&apos;t right.</ErrorNote>
            </div>
          )}
          <Button type="submit" className="mt-6 w-full">
            Enter
          </Button>
        </form>
      </main>
    </div>
  );
}

import type { ReactNode } from "react";

export function Button({
  children,
  variant = "primary",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "quiet" | "danger" }) {
  const styles = {
    primary: "bg-accent text-white hover:bg-accent-hover disabled:bg-faint",
    quiet: "bg-surface text-ink border border-border-strong hover:bg-sunken disabled:text-faint",
    danger: "bg-surface text-incorrect border border-incorrect/40 hover:bg-incorrect/5",
  }[variant];

  return (
    <button
      {...props}
      className={`rounded px-3 py-2 text-sm font-medium transition-colors
                  disabled:cursor-not-allowed ${styles} ${props.className ?? ""}`}
    >
      {children}
    </button>
  );
}

export function Panel({
  title,
  children,
  aside,
}: {
  title: string;
  children: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <section className="rounded border border-border-subtle bg-surface">
      <header className="flex items-baseline justify-between gap-3 border-b border-border-subtle px-4 py-3">
        <h2 className="text-sm font-semibold tracking-wide text-ink uppercase">{title}</h2>
        {aside}
      </header>
      <div className="p-4">{children}</div>
    </section>
  );
}

/** Severity as a word plus a colour, never a colour alone. */
export function SeverityTag({ kind, priority }: { kind: string; priority: number }) {
  const colour =
    priority <= 1 ? "text-sev1 border-sev1/30 bg-sev1/5"
    : priority === 2 ? "text-sev2 border-sev2/30 bg-sev2/5"
    : "text-sev3 border-sev3/30 bg-sev3/5";
  return (
    <span className={`rounded border px-1.5 py-0.5 font-mono text-[11px] ${colour}`}>
      {kind.replace(/_/g, " ")}
    </span>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <p role="status" className="py-6 text-center text-sm text-muted">
      {children}
    </p>
  );
}

export function ErrorNote({ children }: { children: ReactNode }) {
  return (
    <p role="alert" className="rounded border border-incorrect/30 bg-incorrect/5 px-3 py-2 text-sm text-incorrect">
      {children}
    </p>
  );
}

export function Skeleton({ rows = 3, label }: { rows?: number; label: string }) {
  return (
    <div aria-busy="true" aria-label={label} className="space-y-2">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-9 animate-pulse rounded bg-sunken" />
      ))}
    </div>
  );
}

/** The development identity banner. Deliberately hard to mistake for a product. */
export function DevBanner({ who, onSwitch }: { who: string; onSwitch: () => void }) {
  return (
    <div className="border-b border-border-subtle bg-sunken px-4 py-1.5 text-xs text-muted">
      <div className="mx-auto flex max-w-5xl items-center justify-between gap-3">
        <span>
          Development build · acting as <strong className="font-mono text-ink">{who}</strong> ·
          not authentication, not for student use
        </span>
        <button onClick={onSwitch} className="underline underline-offset-2 hover:text-ink">
          switch
        </button>
      </div>
    </div>
  );
}

"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { mutate } from "swr";
import { api, ApiError } from "@/lib/api";
import { meKey } from "@/lib/session";
import { AuthLayout } from "@/components/auth-layout";
import { DemoSignIn, useDemoSignIn } from "@/components/demo-sign-in";
import { Button, ErrorNote } from "@/components/ui";

export default function StudentJoinPage() {
  const demo = useDemoSignIn();
  if (demo === undefined) return null;
  return demo ? <DemoSignIn role="student" /> : <StudentJoin />;
}

function StudentJoin() {
  const router = useRouter();
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const me = await api.join(code);
      await mutate(meKey(me.role), me, { revalidate: false });
      router.replace("/student");
    } catch (e) {
      setError((e as ApiError).message);
      setBusy(false);
    }
  }

  return (
    <AuthLayout
      role="student"
      title="Sign in as a student"
      lede="Type the code your teacher gave you. Capitals and dashes don't matter."
    >
      <form onSubmit={submit} className="space-y-4">
        <label className="block text-sm font-semibold text-ink">
          Your code
          <input
            required
            autoComplete="off"
            autoCapitalize="characters"
            spellCheck={false}
            placeholder="ABCD-EFGH"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            className="figures mt-1.5 block h-14 w-full rounded-[var(--radius-control)] border border-rule-strong bg-sheet px-3 text-center text-2xl font-bold tracking-[0.2em] text-ink uppercase placeholder:font-normal placeholder:text-faint hover:border-pencil focus:border-ink focus:outline-none"
          />
        </label>
        {error && <ErrorNote>{error}</ErrorNote>}
        <Button type="submit" disabled={busy || !code.trim()} className="h-11 w-full">
          {busy ? "Signing in…" : "Sign in"}
        </Button>
      </form>
    </AuthLayout>
  );
}

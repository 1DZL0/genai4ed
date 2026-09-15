"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import useSWR, { mutate } from "swr";
import { api, ApiError, type Me } from "@/lib/api";
import { homeFor, ME_KEY } from "@/lib/session";
import { AuthLayout, inputClass } from "@/components/auth-layout";
import { Button, ErrorNote, Notice } from "@/components/ui";

/** Whether the server has demo sign-in switched on. `undefined` while asking. */
export function useDemoSignIn(): boolean | undefined {
  const { data } = useSWR("auth/config", api.signInConfig);
  return data?.demo_sign_in;
}

/** Any username and password. The account is made on first use. */
export function DemoSignIn({ role }: { role: Me["role"] }) {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const me = await api.demo(role, username, password);
      await mutate(ME_KEY, me, { revalidate: false });
      router.replace(homeFor(me.role));
    } catch (e) {
      setError((e as ApiError).message);
      setBusy(false);
    }
  }

  return (
    <AuthLayout
      role={role}
      title={role === "teacher" ? "Sign in as a teacher" : "Sign in as a student"}
      lede={
        role === "teacher"
          ? "You'll go to your dashboard, with a sample lesson already running."
          : "You'll see every lesson that's open for you."
      }
    >
      <div className="mb-5">
        <Notice tone="amber">
          Demo mode: any username and password will work. A new name creates a new{" "}
          {role}. Don&apos;t use your real name.
        </Notice>
      </div>
      <form onSubmit={submit} className="space-y-4">
        <label className="block text-sm font-semibold text-ink">
          Username
          <input
            required
            autoComplete="username"
            autoCapitalize="none"
            spellCheck={false}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className={inputClass}
          />
        </label>
        <label className="block text-sm font-semibold text-ink">
          Password
          <input
            type="password"
            required
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={inputClass}
          />
        </label>
        {error && <ErrorNote>{error}</ErrorNote>}
        <Button type="submit" disabled={busy || !username.trim()} className="h-11 w-full">
          {busy ? "Signing in…" : "Sign in"}
        </Button>
      </form>
    </AuthLayout>
  );
}

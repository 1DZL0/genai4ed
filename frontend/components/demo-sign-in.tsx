"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import useSWR, { mutate } from "swr";
import { api, ApiError, type Me } from "@/lib/api";
import { homeFor, meKey } from "@/lib/session";
import { AuthLayout, inputClass } from "@/components/auth-layout";
import { Button, ErrorNote, Notice } from "@/components/ui";

/** Whether the server has demo sign-in switched on. `undefined` while asking. */
export function useDemoSignIn(): boolean | undefined {
  const { data } = useSWR("auth/config", api.signInConfig);
  return data?.demo_sign_in;
}

// Three standing teachers, so an experiment can come back to the same lessons.
const TEACHERS = ["teacher-1", "teacher-2", "teacher-3"];

/** Any username and password. The account is made on first use. */
export function DemoSignIn({ role }: { role: Me["role"] }) {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function signIn(name: string, pass: string, teacher?: string) {
    setBusy(true);
    setError(null);
    try {
      const me = await api.demo(role, name, pass, teacher);
      await mutate(meKey(me.role), me, { revalidate: false });
      router.replace(homeFor(me.role));
    } catch (e) {
      setError((e as ApiError).message);
      setBusy(false);
    }
  }

  function submit(event: React.FormEvent) {
    event.preventDefault();
    void signIn(username, password);
  }

  return (
    <AuthLayout
      role={role}
      title={
        role === "teacher" ? "Sign in as a teacher" : "Sign in as a student"
      }
      lede={
        role === "teacher"
          ? "You'll go to your dashboard, with a sample maths lesson ready to start."
          : "You'll see every lesson that's open for you."
      }
    >
      <div className="mb-5">
        <Notice tone="amber">
          Demo mode: any username and password will work. A new name creates a
          new {role}. Don&apos;t use your real name. To be teacher and student
          at the same time, open the other one in another tab of this browser.
        </Notice>
      </div>
      <div className="mb-5 flex flex-wrap gap-2">
        {role === "teacher"
          ? TEACHERS.map((name, i) => (
              <Button
                key={name}
                variant="quiet"
                disabled={busy}
                onClick={() => void signIn(name, "demo")}
              >
                Teacher {i + 1}
              </Button>
            ))
          : TEACHERS.map((name, i) => (
              <Button
                key={name}
                variant="quiet"
                disabled={busy}
                // A new pseudonym every time: a fresh student, in this teacher's class only.
                onClick={() =>
                  void signIn(
                    `student-${Math.floor(1000 + Math.random() * 9000)}`,
                    "demo",
                    name,
                  )
                }
              >
                New student of Teacher {i + 1}
              </Button>
            ))}
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
        <Button
          type="submit"
          disabled={busy || !username.trim()}
          className="h-11 w-full"
        >
          {busy ? "Signing in…" : "Sign in"}
        </Button>
      </form>
    </AuthLayout>
  );
}

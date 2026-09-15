"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { mutate } from "swr";
import { api, ApiError } from "@/lib/api";
import { ME_KEY } from "@/lib/session";
import { AuthLayout, inputClass } from "@/components/auth-layout";
import { DemoSignIn, useDemoSignIn } from "@/components/demo-sign-in";
import { Button, ErrorNote } from "@/components/ui";

export default function TeacherLoginPage() {
  const demo = useDemoSignIn();
  if (demo === undefined) return null;
  return demo ? <DemoSignIn role="teacher" /> : <TeacherLogin />;
}

function TeacherLogin() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const me = await api.login(email, password);
      await mutate(ME_KEY, me, { revalidate: false });
      router.replace("/teacher");
    } catch (e) {
      setError((e as ApiError).message);
      setBusy(false);
    }
  }

  return (
    <AuthLayout
      role="teacher"
      title="Sign in as a teacher"
      lede="Use the email and password from your school's administrator."
    >
      <form onSubmit={submit} className="space-y-4">
        <label className="block text-sm font-semibold text-ink">
          Email
          <input
            type="email"
            autoComplete="username"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className={inputClass}
          />
        </label>
        <label className="block text-sm font-semibold text-ink">
          Password
          <input
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={inputClass}
          />
        </label>
        {error && <ErrorNote>{error}</ErrorNote>}
        <Button type="submit" disabled={busy} className="h-11 w-full">
          {busy ? "Signing in…" : "Sign in"}
        </Button>
      </form>
    </AuthLayout>
  );
}

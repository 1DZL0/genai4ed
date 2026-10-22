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

function teacherLabel(name: string): string {
  const i = TEACHERS.indexOf(name.toLowerCase());
  return i >= 0 ? `Teacher ${i + 1}` : name;
}

/** A fresh pseudonym for a new demo student, from a million, so two presses don't meet. */
function newStudentName(): string {
  const n = new Uint32Array(1);
  crypto.getRandomValues(n);
  return `student-${100000 + (n[0] % 900000)}`;
}

/** The teacher a teacher's own "Student side" link names, so their students join their class.
 * Read once on the client: this form renders only after the browser has asked the server. */
function teacherFromLink(): string {
  if (typeof window === "undefined") return "";
  return new URLSearchParams(window.location.search).get("teacher")?.trim() ?? "";
}

/** Any username and password. The account is made on first use. */
export function DemoSignIn({ role }: { role: Me["role"] }) {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [from] = useState(teacherFromLink);
  // The teacher whose class a new student joins; left empty, a returning student keeps theirs.
  const [teacher, setTeacher] = useState(from);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const teachers = Array.from(new Set([...(from ? [from] : []), ...TEACHERS]));

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
    void signIn(username, password, role === "student" ? teacher.trim() || undefined : undefined);
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
          : teachers.map((name) => (
              <Button
                key={name}
                variant="quiet"
                disabled={busy}
                // A new pseudonym every time: a fresh student, in this teacher's class only.
                onClick={() => void signIn(newStudentName(), "demo", name)}
              >
                New student of {teacherLabel(name)}
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
        {role === "student" && (
          <label className="block text-sm font-semibold text-ink">
            Your teacher&apos;s username
            <input
              list="demo-teachers"
              autoComplete="off"
              autoCapitalize="none"
              spellCheck={false}
              value={teacher}
              onChange={(e) => setTeacher(e.target.value)}
              placeholder="teacher-1"
              className={inputClass}
            />
            <datalist id="demo-teachers">
              {teachers.map((name) => (
                <option key={name} value={name} />
              ))}
            </datalist>
            <span className="mt-1 block text-xs font-normal text-pencil">
              Needed the first time, to join their class. Leave it empty to keep
              the classes you are in.
            </span>
          </label>
        )}
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

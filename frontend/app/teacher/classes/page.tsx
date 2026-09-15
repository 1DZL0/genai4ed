"use client";

import { useState } from "react";
import useSWR from "swr";
import { api, ApiError, type ClassOut, type JoinCode, type RosterEntry } from "@/lib/api";
import { useSignedIn } from "@/lib/session";
import { AppHeader, PageTitle } from "@/components/app-header";
import { Button, Empty, ErrorNote, Notice, Panel, Skeleton } from "@/components/ui";

export default function Classes() {
  const me = useSignedIn("teacher");
  const { data: classes, error } = useSWR<ClassOut[]>(me ? "classes" : null, api.classes);

  if (!me) return null;

  return (
    <>
      <AppHeader me={me} />
      <main className="mx-auto w-full max-w-4xl px-4 py-10 sm:px-6">
        <PageTitle lede="Students sign in with a code from you. Give each student the code next to their name on your list. The platform never learns who they are.">
          Classes
        </PageTitle>

        {error && <ErrorNote>{(error as ApiError).message}</ErrorNote>}
        {!error && !classes && <Skeleton label="Loading your classes" rows={2} />}
        {classes?.length === 0 && (
          <div className="rounded-[var(--radius-sheet)] border border-dashed border-rule-strong px-5">
            <Empty>You don&apos;t have any classes yet.</Empty>
          </div>
        )}
        <div className="space-y-6">
          {classes?.map((klass) => (
            <ClassPanel key={klass.id} klass={klass} />
          ))}
        </div>
      </main>
    </>
  );
}

function ClassPanel({ klass }: { klass: ClassOut }) {
  const { data: roster, mutate } = useSWR<RosterEntry[]>(["roster", klass.id], () =>
    api.roster(klass.id),
  );
  // Codes exist only in this response: the server keeps digests, not codes.
  const [issued, setIssued] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function issue(student?: RosterEntry) {
    const replacing = student ? student.has_join_code : roster?.some((r) => r.has_join_code);
    if (
      replacing &&
      !window.confirm(
        student
          ? `Give ${student.pseudonym} a new code? Their old code stops working and they're signed out.`
          : `Give everyone in ${klass.label} a new code? All the old codes stop working and everyone is signed out.`,
      )
    ) {
      return;
    }
    setBusy(student?.student_id ?? "all");
    setError(null);
    try {
      const codes: JoinCode[] = await api.issueJoinCodes(klass.id, student?.student_id);
      setIssued((prev) => ({
        ...prev,
        ...Object.fromEntries(codes.map((c) => [c.student_id, c.code])),
      }));
      await mutate();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(null);
    }
  }

  const anyShown = Object.keys(issued).length > 0;

  return (
    <Panel
      title={klass.label}
      description={`${klass.students} student${klass.students === 1 ? "" : "s"}`}
      flush
      aside={
        <Button
          variant="quiet"
          size="sm"
          onClick={() => issue()}
          disabled={busy !== null || !roster?.length}
          className="no-print"
        >
          {busy === "all" ? "Making codes…" : "New codes for everyone"}
        </Button>
      }
    >
      {error && (
        <div className="px-5 pb-3">
          <ErrorNote>{error}</ErrorNote>
        </div>
      )}
      {!roster && (
        <div className="px-5 pb-5">
          <Skeleton label={`Loading ${klass.label}`} rows={2} />
        </div>
      )}
      {roster?.length === 0 && (
        <div className="px-5">
          <Empty>No students are in this class yet.</Empty>
        </div>
      )}
      {roster && roster.length > 0 && (
        <>
          {anyShown && (
            <div className="px-5 pb-3">
              <Notice tone="amber">
                You&apos;ll only see these codes once. Write them down or{" "}
                <button onClick={() => window.print()} className="font-semibold underline underline-offset-4">
                  print this page
                </button>{" "}
                before you leave.
              </Notice>
            </div>
          )}
          <table className="w-full border-t border-rule text-sm">
            <thead>
              <tr className="text-left text-xs text-pencil">
                <th scope="col" className="py-2.5 pr-3 pl-5 font-semibold">
                  Student
                </th>
                <th scope="col" className="px-3 py-2.5 font-semibold">
                  Sign-in code
                </th>
                <th scope="col" className="py-2.5 pr-5 pl-3">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {roster.map((student) => (
                <tr key={student.student_id} className="border-t border-rule">
                  <th scope="row" className="figures py-3 pr-3 pl-5 text-left font-bold text-ink">
                    {student.pseudonym}
                  </th>
                  <td className="px-3 py-3">
                    {issued[student.student_id] ? (
                      <span className="figures text-lg font-bold tracking-[0.12em] text-ink">
                        {issued[student.student_id]}
                      </span>
                    ) : (
                      <span className="text-pencil">
                        {student.has_join_code ? "Given out" : "No code yet"}
                      </span>
                    )}
                  </td>
                  <td className="py-3 pr-5 pl-3 text-right">
                    <Button
                      variant="plain"
                      onClick={() => issue(student)}
                      disabled={busy !== null}
                      className="no-print text-sm"
                    >
                      {busy === student.student_id
                        ? "Making code…"
                        : student.has_join_code
                          ? "New code"
                          : "Make a code"}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </Panel>
  );
}

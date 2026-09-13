/**
 * Typed access to the backend.
 *
 * Identity is the development pseudonym header - the same seam the backend
 * documents as NOT authentication. It is replaced by school-managed identity
 * in one place, here and in app/auth.py, without touching any component.
 */

// Relative by default: requests go to the origin that served the page and
// Next forwards them to the API (see next.config.ts). Set
// NEXT_PUBLIC_API_BASE only to point the browser at an API directly.
const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

export type SessionSummary = {
  session_id: string;
  title: string;
  status: string;
  closes_at: string;
  items: number;
};

export type Item = {
  id: string;
  ordinal: number;
  prompt: string;
  attempts: number;
};

export type StudentSession = {
  session_id: string;
  status: string;
  title: string;
  material_notes: string | null;
  disclosure: string;
  items: Item[];
};

export type AttemptResult = {
  attempt_id: string;
  correct: boolean;
  attempt_index: number;
  tutor_message: string;
  help_given: boolean;
  teacher_notified: boolean;
};

export type StudentProgress = {
  student_id: string;
  pseudonym: string;
  attempted: number;
  correct: number;
  attempts: number;
};

export type QueueItem = {
  id: string;
  student_id: string;
  pseudonym: string;
  kind: string;
  priority: number;
  summary: string;
  supporting_record_ids: string[];
  created_at: string;
};

export type TeacherSessionSummary = {
  session_id: string;
  title: string;
  status: string;
  class_label: string;
  closes_at: string;
  open_exceptions: number;
};

export const RUNGS = [
  "attempt",
  "diagnostic_question",
  "conceptual_cue",
  "targeted_hint",
  "analogous_example",
  "partial_step",
  "full_solution",
] as const;
export type Rung = (typeof RUNGS)[number];

/** Rungs a teacher writes wording for. `attempt` is the student working alone. */
export const HINTABLE_RUNGS = RUNGS.slice(1) as readonly Rung[];

export type MisconceptionIn = { code: string; label: string };

export type ItemIn = {
  prompt: string;
  expected_answer: string;
  hint_templates: Partial<Record<Rung, string>>;
  misconception_vocabulary: MisconceptionIn[];
};

export type ContractIn = {
  title: string;
  subject: string;
  objective_code: string;
  objective_title: string;
  class_id: string;
  max_rung: Rung;
  allow_full_solution: boolean;
  repeated_incorrect: number;
  repeated_misconception: number;
  confidence_floor: number;
  notes: string;
  items: ItemIn[];
};

export type ContractOut = {
  id: string;
  title: string;
  status: string;
  version: number;
  items: number;
  max_rung: string;
  allow_full_solution: boolean;
};

export type Console = {
  session_id: string;
  status: string;
  title: string;
  items: number;
  progress: StudentProgress[];
  queue: QueueItem[];
};

export type TranscriptLine = {
  record_id: string;
  kind: string;
  correct: boolean | null;
  detail: Record<string, unknown>;
  created_at: string;
};

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, pseudonym: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-GenAI4ED-Pseudonym": pseudonym,
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      /* a non-JSON error body is still an error */
    }
    throw new ApiError(response.status, detail);
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

export const api = {
  base: BASE,

  mySessions: (who: string) => request<SessionSummary[]>("/api/sessions", who),

  studentSession: (who: string, id: string) =>
    request<StudentSession>(`/api/sessions/${id}`, who),

  submitAttempt: (who: string, id: string, itemId: string, answer: string) =>
    request<AttemptResult>(`/api/sessions/${id}/attempts`, who, {
      method: "POST",
      body: JSON.stringify({ item_id: itemId, answer }),
    }),

  requestTeacher: (who: string, id: string) =>
    request<{ status: string }>(`/api/sessions/${id}/request-teacher`, who, { method: "POST" }),

  contracts: (who: string) => request<ContractOut[]>("/api/teacher/contracts", who),

  createContract: (who: string, body: ContractIn) =>
    request<ContractOut>("/api/teacher/contracts", who, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  activateContract: (who: string, id: string) =>
    request<ContractOut>(`/api/teacher/contracts/${id}/activate`, who, { method: "POST" }),

  openSession: (who: string, id: string, minutes: number) =>
    request<{ session_id: string; closes_at: string; students: number }>(
      `/api/teacher/contracts/${id}/sessions?minutes=${minutes}`,
      who,
      { method: "POST" },
    ),

  teacherSessions: (who: string) =>
    request<TeacherSessionSummary[]>("/api/teacher/sessions", who),

  console: (who: string, id: string) =>
    request<Console>(`/api/teacher/sessions/${id}/console`, who),

  acknowledge: (who: string, exceptionId: string) =>
    request<QueueItem>(`/api/teacher/exceptions/${exceptionId}/acknowledge`, who, {
      method: "POST",
    }),

  transcript: (who: string, sessionId: string, studentId: string) =>
    request<TranscriptLine[]>(
      `/api/teacher/sessions/${sessionId}/students/${studentId}/transcript`,
      who,
    ),

  setSessionState: (who: string, id: string, to: "open" | "paused" | "closed") =>
    request<Console>(`/api/teacher/sessions/${id}/state?to=${to}`, who, { method: "POST" }),

  // The console polls rather than using the SSE endpoint. EventSource cannot
  // send custom headers, so it cannot carry the development pseudonym, and
  // adding a query-parameter identity path would create a second way in that
  // could outlive the development seam. Concept note S3 offers polling as an
  // equally sufficient option for a class of 25-30. The SSE endpoint stays on
  // the backend for when real cookie-based auth exists.
};

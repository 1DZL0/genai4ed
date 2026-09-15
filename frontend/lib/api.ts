/**
 * Typed access to the backend.
 *
 * Identity travels in an HttpOnly session cookie the browser sends by itself,
 * so nothing here handles a token and page scripts cannot read one.
 */

// Relative by default: requests go to the origin that served the page and
// Next forwards them to the API (see next.config.ts). That same-origin path is
// also what lets the session cookie flow without any CORS arrangement.
const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

export type Me = {
  pseudonym: string;
  role: "teacher" | "student";
  email: string | null;
};

export type SessionSummary = {
  session_id: string;
  title: string;
  subject: string;
  status: string;
  closes_at: string;
  items: number;
};

export type HistoryLine = {
  kind: "attempt" | "hint" | "teacher";
  text: string;
  correct: boolean | null;
  at: string;
};

export type Item = {
  id: string;
  ordinal: number;
  prompt: string;
  attempts: number;
  solved: boolean;
  history: HistoryLine[];
};

export type StudentSession = {
  session_id: string;
  status: string;
  closes_at: string;
  title: string;
  subject: string;
  material_notes: string | null;
  disclosure: string;
  items: Item[];
  teacher_messages: HistoryLine[];
};

export type AttemptResult = {
  attempt_id: string;
  correct: boolean;
  attempt_index: number;
  tutor_message: string;
  help_given: boolean;
  teacher_notified: boolean;
};

export type RegisterCell = {
  item_id: string;
  attempts: number;
  solved: boolean;
  rung: string | null;
};

export type StudentProgress = {
  student_id: string;
  pseudonym: string;
  attempted: number;
  correct: number;
  attempts: number;
  needs_you: boolean;
  cells: RegisterCell[];
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
  subject: string;
  status: string;
  class_label: string;
  closes_at: string;
  open_exceptions: number;
};

export type ClassOut = { id: string; label: string; students: number };

export type RosterEntry = { student_id: string; pseudonym: string; has_join_code: boolean };

export type JoinCode = { student_id: string; pseudonym: string; code: string };

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
  subject: string;
  status: string;
  version: number;
  items: number;
  max_rung: string;
  allow_full_solution: boolean;
};

export type Console = {
  session_id: string;
  status: string;
  closes_at: string;
  title: string;
  subject: string;
  class_label: string;
  items: number;
  item_list: { id: string; ordinal: number; prompt: string }[];
  rungs: string[];
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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    credentials: "same-origin",
    cache: "no-store",
  });

  if (!response.ok) {
    // A sign-in that expired mid-lesson: go back to the front door rather than
    // leave a page full of errors. The sign-in calls report their own 401s.
    // A full reload, as on sign-out: there is no router here, and it clears
    // every cached response from the expired session.
    if (response.status === 401 && !path.startsWith("/api/auth/") && typeof window !== "undefined") {
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.assign("/");
    }
    let detail = response.statusText;
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      /* a non-JSON error body is still an error */
    }
    throw new ApiError(response.status, typeof detail === "string" ? detail : "Request failed.");
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

const post = (body?: unknown): RequestInit => ({
  method: "POST",
  body: body === undefined ? undefined : JSON.stringify(body),
});

export const api = {
  base: BASE,

  me: () => request<Me>("/api/auth/me"),
  signInConfig: () => request<{ demo_sign_in: boolean }>("/api/auth/config"),
  demo: (role: Me["role"], username: string, password: string) =>
    request<Me>("/api/auth/demo", post({ role, username, password })),
  login: (email: string, password: string) =>
    request<Me>("/api/auth/login", post({ email, password })),
  join: (code: string) => request<Me>("/api/auth/join", post({ code })),
  logout: () => request<void>("/api/auth/logout", post()),

  mySessions: () => request<SessionSummary[]>("/api/sessions"),

  studentSession: (id: string) => request<StudentSession>(`/api/sessions/${id}`),

  submitAttempt: (id: string, itemId: string, answer: string) =>
    request<AttemptResult>(`/api/sessions/${id}/attempts`, post({ item_id: itemId, answer })),

  requestTeacher: (id: string) =>
    request<{ status: string }>(`/api/sessions/${id}/request-teacher`, post()),

  classes: () => request<ClassOut[]>("/api/teacher/classes"),

  roster: (classId: string) => request<RosterEntry[]>(`/api/teacher/classes/${classId}/students`),

  issueJoinCodes: (classId: string, studentId?: string) =>
    request<JoinCode[]>(
      `/api/teacher/classes/${classId}/join-codes${studentId ? `?student_id=${studentId}` : ""}`,
      post(),
    ),

  contracts: () => request<ContractOut[]>("/api/teacher/contracts"),

  createContract: (body: ContractIn) => request<ContractOut>("/api/teacher/contracts", post(body)),

  activateContract: (id: string) =>
    request<ContractOut>(`/api/teacher/contracts/${id}/activate`, post()),

  openSession: (id: string, minutes: number) =>
    request<{ session_id: string; closes_at: string; students: number }>(
      `/api/teacher/contracts/${id}/sessions?minutes=${minutes}`,
      post(),
    ),

  teacherSessions: () => request<TeacherSessionSummary[]>("/api/teacher/sessions"),

  console: (id: string) => request<Console>(`/api/teacher/sessions/${id}/console`),

  acknowledge: (exceptionId: string) =>
    request<QueueItem>(`/api/teacher/exceptions/${exceptionId}/acknowledge`, post()),

  transcript: (sessionId: string, studentId: string) =>
    request<TranscriptLine[]>(
      `/api/teacher/sessions/${sessionId}/students/${studentId}/transcript`,
    ),

  messageStudent: (sessionId: string, studentId: string, text: string) =>
    request<{ status: string }>(
      `/api/teacher/sessions/${sessionId}/students/${studentId}/message`,
      post({ text }),
    ),

  setSessionState: (id: string, to: "open" | "paused" | "closed") =>
    request<Console>(`/api/teacher/sessions/${id}/state?to=${to}`, post()),
};

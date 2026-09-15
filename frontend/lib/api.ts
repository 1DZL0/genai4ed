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

export type ClassOut = { id: string; label: string; students: number };

export type RosterEntry = { student_id: string; pseudonym: string; has_join_code: boolean };

export type JoinCode = { student_id: string; pseudonym: string; code: string };

export type LessonSummary = {
  lesson_id: string;
  plan_version_id: string;
  title: string;
  subject: string;
  class_label: string;
  status: string;
  plan_version: number;
  scheduled_for: string | null;
  opened_at: string | null;
  closes_at: string | null;
  closed_at: string | null;
  students: number;
  steps: number;
  open_exceptions: number;
  outcomes_to_confirm: number;
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
    // A file upload sets its own multipart boundary; everything else is JSON.
    headers:
      typeof FormData !== "undefined" && init?.body instanceof FormData
        ? { ...(init?.headers ?? {}) }
        : { "Content-Type": "application/json", ...(init?.headers ?? {}) },
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

/* ---------- the class agent ---------- */

export type Signal =
  | "struggling"
  | "misconception"
  | "manipulation_attempt"
  | "off_task"
  | "fast_progress"
  | "unresolved_question"
  | "wellbeing"
  | "asked_for_teacher";

export type BriefStep = {
  name: string;
  kind: "explain" | "question" | "practice" | "check";
  goal: string;
  prompt_ideas: string[];
  success_criteria: string[];
  reference_answer: string | null;
};

export type PolicyRules = {
  hints_allowed: boolean;
  partial_after_attempts: number;
  full_answer_after_attempts: number | null;
  may_write_for_student: boolean;
  escalations: { signal: Signal; after: number; action: "log" | "summarise" | "alert" }[];
  notes: string[];
};

export type LessonBrief = {
  title: string;
  subject: string;
  year_group: string;
  duration_minutes: number;
  prior_knowledge: string;
  objectives: string[];
  strategy: string;
  steps: BriefStep[];
  assessment: { name: string; max: number; description: string }[];
  rules_text: string;
  rules: PolicyRules;
  topics: string[];
};

export type AgentMessage = {
  id: string;
  role: "teacher" | "student" | "agent" | "event";
  text: string;
  data: Record<string, unknown>;
  material_ids: string[];
  created_at: string;
};

export type MaterialOut = {
  id: string;
  filename: string;
  media_type: string;
  size_bytes: number;
  readable: boolean;
};

export type LessonRun = {
  lesson_id: string;
  class_label: string;
  status: string;
  opened_at: string | null;
  closed_at: string | null;
  open_alerts: number;
};

export type Design = {
  id: string;
  plan_id: string;
  version: number;
  status: "draft" | "active" | "closed";
  title: string;
  subject: string;
  brief: LessonBrief;
  rules_in_words: string[];
  missing: string[];
  approved_version_id: string | null;
  materials: MaterialOut[];
  messages: AgentMessage[];
  runs: LessonRun[];
};

export type DesignCard = {
  id: string;
  plan_id: string;
  version: number;
  status: "draft" | "active" | "closed";
  title: string;
  subject: string;
  duration_minutes: number;
  steps: number;
  objectives: string[];
  approved_version_id: string | null;
  live: LessonRun | null;
  last_run: LessonRun | null;
  updated_at: string;
};

export type LearnLine = { id: string; who: "student" | "agent" | "note"; text: string; at: string };

export type Learn = {
  session_id: string;
  status: string;
  closes_at: string | null;
  title: string;
  subject: string;
  steps: { name: string; state: "done" | "current" | "todo" }[];
  step_index: number;
  completed: boolean;
  task: string | null;
  lines: LearnLine[];
  can_talk: boolean;
  disclosure: string;
};

export type LearnCard = {
  session_id: string;
  title: string;
  subject: string;
  status: string;
  closes_at: string | null;
  steps: number;
  completed: boolean;
};

export type Intent = "dont_understand" | "another_way" | "example" | "why_wrong";

export type StudentState = {
  student_id: string;
  pseudonym: string;
  state: "needs_you" | "struggling" | "working" | "finished" | "not_started";
  step_index: number;
  step_name: string;
  turns: number;
  last_activity_at: string | null;
  note: string;
  open_alerts: number;
};

export type LiveAlert = {
  id: string;
  student_id: string;
  pseudonym: string;
  kind: string;
  priority: number;
  summary: string;
  created_at: string;
};

export type Live = {
  lesson_id: string;
  design_id: string;
  title: string;
  subject: string;
  class_label: string;
  status: string;
  opened_at: string | null;
  closes_at: string | null;
  steps: string[];
  students: StudentState[];
  alerts: LiveAlert[];
  patterns: { note: string; students: string[] }[];
  notable: { kind: string; pseudonym: string; note: string; at: string }[];
  insight: { summary: string; items: { text: string; students: string[] }[]; created_at: string } | null;
  conversation: { id: string; role: string; text: string; created_at: string }[];
};

export type StudentDetail = {
  student_id: string;
  pseudonym: string;
  state: StudentState["state"];
  summary: string[];
  steps: { name: string; judgment: string | null; attempts: number; current: boolean }[];
  evidence: { kind: string; text: string; detail: string; at: string }[];
  conversation: { who: "student" | "agent" | "note" | "teacher_only"; text: string; at: string }[] | null;
};

export type Outcome = {
  id: string;
  student_id: string;
  pseudonym: string;
  status: "suggested" | "confirmed";
  suggested: { criteria: { name: string; points: number; max: number; reason?: string }[]; keep: string; develop: string[] };
  suggested_total: number;
  confirmed: { criteria: { name: string; points: number; max: number }[]; keep: string; develop: string[] } | null;
  confirmed_total: number | null;
  comment: string | null;
  out_of: number;
};

export type ReviewPage = {
  live: Live;
  criteria: { name: string; max: number; description: string }[];
  outcomes: Outcome[];
  students_without_outcome: string[];
};

export const agentApi = {
  live: (lessonId: string) => request<Live>(`/api/teacher/live/${lessonId}`),

  askClass: (lessonId: string, text: string) =>
    request<Live>(`/api/teacher/live/${lessonId}/ask`, post({ text })),

  refreshInsight: (lessonId: string) =>
    request<Live>(`/api/teacher/live/${lessonId}/insight`, post()),

  studentDetail: (lessonId: string, studentId: string, withConversation = false) =>
    request<StudentDetail>(
      `/api/teacher/live/${lessonId}/students/${studentId}${withConversation ? "?conversation=true" : ""}`,
    ),

  guide: (lessonId: string, studentId: string, text: string, showToStudent: boolean) =>
    request<StudentDetail>(
      `/api/teacher/live/${lessonId}/students/${studentId}/guide`,
      post({ text, show_to_student: showToStudent }),
    ),

  review: (lessonId: string) => request<ReviewPage>(`/api/teacher/live/${lessonId}/review`),

  suggestOutcomes: (lessonId: string) =>
    request<ReviewPage>(`/api/teacher/live/${lessonId}/outcomes`, post()),

  confirmOutcome: (lessonId: string, outcomeId: string, points: Record<string, number>, comment: string) =>
    request<ReviewPage>(
      `/api/teacher/live/${lessonId}/outcomes/${outcomeId}/confirm`,
      post({ points, comment: comment.trim() || null }),
    ),

  myLessons: () => request<LearnCard[]>("/api/learn"),

  learn: (sessionId: string) => request<Learn>(`/api/learn/${sessionId}`),

  learnStart: (sessionId: string) => request<Learn>(`/api/learn/${sessionId}/start`, post()),

  learnSay: (sessionId: string, text: string, intent?: Intent) =>
    request<Learn>(`/api/learn/${sessionId}/messages`, post({ text, intent: intent ?? null })),

  learnAskTeacher: (sessionId: string) =>
    request<Learn>(`/api/learn/${sessionId}/request-teacher`, post()),

  designs: () => request<DesignCard[]>("/api/teacher/designs"),

  startDesign: (text: string) => request<Design>("/api/teacher/designs", post({ text })),

  design: (id: string) => request<Design>(`/api/teacher/designs/${id}`),

  talk: (id: string, text: string, materialIds: string[] = []) =>
    request<Design>(
      `/api/teacher/designs/${id}/messages`,
      post({ text, material_ids: materialIds }),
    ),

  uploadMaterial: (id: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<MaterialOut>(`/api/teacher/designs/${id}/materials`, {
      method: "POST",
      body: form,
    });
  },

  removeMaterial: (id: string, materialId: string) =>
    request<void>(`/api/teacher/designs/${id}/materials/${materialId}`, { method: "DELETE" }),

  approveDesign: (id: string) => request<Design>(`/api/teacher/designs/${id}/approve`, post()),

  designSettings: (id: string, usePastLessons: boolean) =>
    request<Design>(
      `/api/teacher/designs/${id}/settings`,
      post({ use_past_lessons: usePastLessons }),
    ),

  deleteDesign: (id: string) =>
    request<void>(`/api/teacher/designs/${id}`, { method: "DELETE" }),
};

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

  classes: () => request<ClassOut[]>("/api/teacher/classes"),

  roster: (classId: string) => request<RosterEntry[]>(`/api/teacher/classes/${classId}/students`),

  createClass: (label: string, students: number) =>
    request<ClassOut>("/api/teacher/classes", post({ label, students })),

  addStudent: (classId: string) =>
    request<RosterEntry>(`/api/teacher/classes/${classId}/students`, post()),

  removeStudent: (classId: string, studentId: string) =>
    request<void>(`/api/teacher/classes/${classId}/students/${studentId}`, { method: "DELETE" }),

  issueJoinCodes: (classId: string, studentId?: string) =>
    request<JoinCode[]>(
      `/api/teacher/classes/${classId}/join-codes${studentId ? `?student_id=${studentId}` : ""}`,
      post(),
    ),

  bookLesson: (planVersionId: string, classId: string, scheduledFor?: string) =>
    request<LessonSummary>(
      "/api/teacher/lessons",
      post({ plan_version_id: planVersionId, class_id: classId, scheduled_for: scheduledFor }),
    ),

  startLesson: (id: string) => request<LessonSummary>(`/api/teacher/lessons/${id}/start`, post()),

  acknowledge: (exceptionId: string) =>
    request<{ id: string; kind: string }>(
      `/api/teacher/exceptions/${exceptionId}/acknowledge`,
      post(),
    ),

  setSessionState: (id: string, to: "open" | "paused" | "closed") =>
    request<{ session_id: string; status: string; closed_at: string | null }>(
      `/api/teacher/sessions/${id}/state?to=${to}`,
      post(),
    ),
};

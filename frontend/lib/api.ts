/** Typed access to the backend. Identity is an HttpOnly cookie the browser sends by itself. */

// Relative by default: Next forwards same-origin /api requests to the backend (next.config.ts).
const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

export type Me = {
  pseudonym: string;
  role: "teacher" | "student";
  email: string | null;
};

export type ClassOut = { id: string; label: string; students: number };

export type RosterEntry = {
  student_id: string;
  pseudonym: string;
  has_join_code: boolean;
};

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
      init?.body instanceof FormData
        ? init?.headers
        : { "Content-Type": "application/json", ...init?.headers },
    credentials: "same-origin",
    cache: "no-store",
  });

  if (!response.ok) {
    // A sign-in that expired mid-lesson: a full reload to the front door also drops every cached response.
    if (
      response.status === 401 &&
      !path.startsWith("/api/auth/") &&
      typeof window !== "undefined"
    ) {
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.assign("/");
    }
    let detail = response.statusText;
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      /* a non-JSON error body is still an error */
    }
    throw new ApiError(
      response.status,
      typeof detail === "string" ? detail : "Request failed.",
    );
  }
  return response.status === 204
    ? (undefined as T)
    : ((await response.json()) as T);
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
  escalations: {
    signal: Signal;
    after: number;
    action: "log" | "summarise" | "alert";
  }[];
  notes: string[];
};

export type LessonRun = {
  session_id: string;
  class_label: string;
  status: string;
  opened_at: string | null;
  closed_at: string | null;
  open_alerts: number;
  outcomes_to_confirm: number;
};

export type LearnLine = {
  id: string;
  who: "student" | "agent" | "note";
  text: string;
  at: string;
};

/** What the teacher confirmed. Nothing else about marks ever reaches a student. */
export type LearnResult = {
  total: number;
  out_of: number;
  criteria: { name: string; points: number; max: number }[];
  comment: string | null;
};

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
  result: LearnResult | null;
};

export type LearnCard = {
  session_id: string;
  title: string;
  subject: string;
  status: string;
  closes_at: string | null;
  steps: number;
  completed: boolean;
  result: LearnResult | null;
};

export type Intent =
  "dont_understand" | "another_way" | "example" | "why_wrong";

export type StudentState = {
  student_id: string;
  pseudonym: string;
  state:
    | "needs_you"
    | "struggling"
    | "working"
    | "finished"
    | "not_started"
    | "took_part";
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

export type Outcome = {
  id: string;
  student_id: string;
  pseudonym: string;
  status: "suggested" | "confirmed";
  suggested: {
    criteria: { name: string; points: number; max: number; reason?: string }[];
    keep: string;
    develop: string[];
  };
  suggested_total: number;
  confirmed: {
    criteria: { name: string; points: number; max: number }[];
    keep: string;
    develop: string[];
  } | null;
  confirmed_total: number | null;
  comment: string | null;
  out_of: number;
};

/* ---------- the teacher's thread ----------
 * One conversation is the whole teacher interface. The server builds every card from records;
 * anything that changes state is an action. */

export type LessonCard = {
  type: "lesson";
  lesson_id: string;
  plan_id: string;
  version: number;
  status: "draft" | "active" | "closed";
  title: string;
  subject: string;
  duration_minutes: number;
  objectives: string[];
  strategy: string;
  steps: {
    name: string;
    kind: BriefStep["kind"];
    goal: string;
    criteria: string[];
    has_reference: boolean;
  }[];
  assessment: { name: string; max: number; description: string }[];
  rules_text: string;
  rules_in_words: string[];
  missing: string[];
  use_past_lessons: boolean;
  study: boolean;
  approved_lesson_id: string | null;
  materials: { id: string; filename: string; readable: boolean }[];
  classes: ClassOut[];
  live: LessonRun | null;
  runs: LessonRun[];
};

export type LessonsCard = {
  type: "lessons";
  classes: ClassOut[];
  lessons: {
    lesson_id: string;
    title: string;
    subject: string;
    status: "draft" | "active" | "closed";
    steps: number;
    duration_minutes: number;
    ready: boolean;
    live: LessonRun | null;
    last_run: LessonRun | null;
  }[];
};

export type ClassCard = {
  type: "class";
  session_id: string;
  lesson_id: string;
  title: string;
  class_label: string;
  status: string;
  opened_at: string | null;
  closes_at: string | null;
  steps: string[];
  students: StudentState[];
  alerts: LiveAlert[];
  patterns: { note: string; students: string[] }[];
  notable: { kind: string; pseudonym: string; note: string; at: string }[];
};

export type Neighbour = { student_id: string; pseudonym: string };

export type StudentCard = {
  type: "student";
  session_id: string;
  student_id: string;
  pseudonym: string;
  /** Either side of them on the class board. */
  previous: Neighbour | null;
  next: Neighbour | null;
  state: StudentState["state"];
  session_status: string;
  summary: string[];
  steps: {
    name: string;
    judgment: string | null;
    attempts: number;
    current: boolean;
  }[];
  evidence: { kind: string; text: string; detail: string; at: string }[];
  conversation:
    | {
        who: "student" | "agent" | "note" | "teacher_only";
        text: string;
        at: string;
      }[]
    | null;
  /** What the records show they know, by topic, across every lesson. */
  knowledge: {
    topic: string;
    judged: number;
    met: number;
    misconceptions: string[];
  }[];
};

export type OutcomesCard = {
  type: "outcomes";
  session_id: string;
  title: string;
  class_label: string;
  status: string;
  summary: string | null;
  criteria: { name: string; max: number; description: string }[];
  outcomes: Outcome[];
  students_without_outcome: string[];
  took_part: boolean;
  can_suggest: boolean;
};

export type ThreadCard =
  LessonCard | LessonsCard | ClassCard | StudentCard | OutcomesCard;

export type ThreadMessage = {
  id: string;
  role: "teacher" | "agent" | "event";
  text: string;
  material_ids: string[];
  created_at: string;
};

export type StripRow = {
  session_id: string;
  title: string;
  class_label: string;
  status: string;
  closes_at: string | null;
  counts: Partial<Record<StudentState["state"], number>>;
  students: number;
  needs_you_more: number;
  needs_you: {
    exception_id: string;
    student_id: string;
    pseudonym: string;
    kind: string;
    summary: string;
  }[];
};

/** The lesson the next thing the teacher says will change. */
export type Focus = { lesson_id: string; title: string; status: string };

export type Thread = {
  messages: ThreadMessage[];
  strip: StripRow[];
  lessons: number;
  focus: Focus | null;
  /** The one card on screen, beside the conversation rather than in it. */
  showing: ThreadCard | null;
};

export type ThreadAction =
  | { action: "show_lessons" | "new_lesson" | "clear" }
  | {
      action: "show_lesson" | "focus_lesson" | "approve" | "delete_lesson";
      lesson_id: string;
    }
  | { action: "delete_material"; material_id: string }
  | { action: "follow_up"; text: string }
  | { action: "use_past_lessons"; lesson_id: string; value: boolean }
  | { action: "run"; lesson_id: string; class_id: string }
  | {
      action:
        | "show_class"
        | "show_outcomes"
        | "pause"
        | "resume"
        | "end"
        | "suggest_outcomes";
      session_id: string;
    }
  | {
      action: "show_student" | "show_transcript";
      session_id: string;
      student_id: string;
    }
  | {
      action: "guide";
      session_id: string;
      student_id: string;
      text: string;
      show_to_student: boolean;
    }
  | {
      action: "confirm_outcome";
      session_id: string;
      outcome_id: string;
      points: Record<string, number>;
      comment: string | null;
    }
  | { action: "acknowledge"; exception_id: string };

export type ResearchArm = {
  arm: string;
  students: number;
  turns: number;
  conflicts: Record<string, number>;
  held_back: number;
  mean_latency_ms: number;
  mean_suggested: number | null;
  mean_confirmed: number | null;
};

export type ResearchSummary = {
  study: {
    active: boolean;
    policy: string;
    supervisor: boolean;
    model: string;
  };
  lessons: {
    session_id: string;
    lesson: string;
    status: string;
    models: string[];
    prompt_versions: string[];
    alerts: Record<string, number>;
    arms: ResearchArm[];
  }[];
};

export type Instructions = { teacher: string; student: string; review: string };

export const researchApi = {
  summary: (key: string) =>
    request<ResearchSummary>("/api/research/summary", {
      headers: { "X-Research-Key": key },
    }),
  instructions: (key: string) =>
    request<Instructions>("/api/research/instructions", {
      headers: { "X-Research-Key": key },
    }),
  // The records as a zip of CSV files, handed to the browser as a download.
  download: async (key: string, withText: boolean) => {
    const response = await fetch(
      `${BASE}/api/research/export?with_text=${withText}`,
      {
        headers: { "X-Research-Key": key },
        credentials: "same-origin",
      },
    );
    if (!response.ok)
      throw new ApiError(response.status, "The export could not be made.");
    const url = URL.createObjectURL(await response.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = withText
      ? "genai4ed-export-with-text.zip"
      : "genai4ed-export.zip";
    a.click();
    URL.revokeObjectURL(url);
  },
};

export const threadApi = {
  read: () => request<Thread>("/api/teacher/thread"),

  // Browsing lessons is not a turn in the conversation, so it writes nothing.
  lessons: () => request<LessonsCard>("/api/teacher/thread/lessons"),

  say: (text: string) =>
    request<Thread>(
      "/api/teacher/thread/messages",
      post({ text, material_ids: [] }),
    ),

  act: (action: ThreadAction) =>
    request<Thread>("/api/teacher/thread/actions", post(action)),

  attach: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Thread>("/api/teacher/thread/materials", {
      method: "POST",
      body: form,
    });
  },
};

export const agentApi = {
  myLessons: () => request<LearnCard[]>("/api/learn"),

  learn: (sessionId: string) => request<Learn>(`/api/learn/${sessionId}`),

  learnStart: (sessionId: string) =>
    request<Learn>(`/api/learn/${sessionId}/start`, post()),

  learnSay: (sessionId: string, text: string, intent?: Intent) =>
    request<Learn>(
      `/api/learn/${sessionId}/messages`,
      post({ text, intent: intent ?? null }),
    ),

  learnAskTeacher: (sessionId: string) =>
    request<Learn>(`/api/learn/${sessionId}/request-teacher`, post()),
};

export const api = {
  me: (role?: Me["role"]) =>
    request<Me>(`/api/auth/me${role ? `?role=${role}` : ""}`),
  signInConfig: () => request<{ demo_sign_in: boolean }>("/api/auth/config"),
  demo: (
    role: Me["role"],
    username: string,
    password: string,
    teacher?: string,
  ) =>
    request<Me>(
      "/api/auth/demo",
      post({ role, username, password, teacher: teacher ?? null }),
    ),
  login: (email: string, password: string) =>
    request<Me>("/api/auth/login", post({ email, password })),
  join: (code: string) => request<Me>("/api/auth/join", post({ code })),
  logout: (role?: Me["role"]) =>
    request<void>(`/api/auth/logout${role ? `?role=${role}` : ""}`, post()),

  classes: () => request<ClassOut[]>("/api/teacher/classes"),

  roster: (classId: string) =>
    request<RosterEntry[]>(`/api/teacher/classes/${classId}/students`),

  createClass: (label: string, students: number) =>
    request<ClassOut>("/api/teacher/classes", post({ label, students })),

  addStudent: (classId: string) =>
    request<RosterEntry>(`/api/teacher/classes/${classId}/students`, post()),

  removeStudent: (classId: string, studentId: string) =>
    request<void>(`/api/teacher/classes/${classId}/students/${studentId}`, {
      method: "DELETE",
    }),

  issueJoinCodes: (classId: string, studentId?: string) =>
    request<JoinCode[]>(
      `/api/teacher/classes/${classId}/join-codes${studentId ? `?student_id=${studentId}` : ""}`,
      post(),
    ),
};

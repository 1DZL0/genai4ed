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

/** How one student did in one lesson, for a class's progress grid. */
export type ProgressCell = {
  session_id: string;
  state: "finished" | "part" | "opened" | "not_started" | "not_in_lesson";
  steps_done: number;
  steps_total: number;
  /** Only a mark the teacher confirmed. */
  mark: { total: number; out_of: number } | null;
  outcome: "confirmed" | "suggested" | null;
  alerts_open: number;
};

/** Every student down the side, every lesson the class has had across, oldest first. */
export type ClassProgress = {
  class_id: string;
  label: string;
  lessons: {
    session_id: string;
    title: string;
    subject: string;
    date: string | null;
    status: string;
    steps: number;
  }[];
  students: { student_id: string; pseudonym: string; cells: ProgressCell[] }[];
};

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

/** This tab's own id, kept for as long as the tab is open, so two students can each sign in
 * in their own tab of one browser without one taking over the other's lesson. */
function tabId(): string | null {
  if (typeof window === "undefined") return null;
  try {
    let id = sessionStorage.getItem("genai4ed-tab");
    if (!id) {
      id = Array.from(crypto.getRandomValues(new Uint8Array(8)), (b) =>
        b.toString(16).padStart(2, "0"),
      ).join("");
      sessionStorage.setItem("genai4ed-tab", id);
    }
    return id;
  } catch {
    return null; // storage blocked: the browser's one sign-in, as before
  }
}

function withTab(headers?: HeadersInit): HeadersInit {
  const tab = tabId();
  return tab ? { ...(headers as Record<string, string>), "X-Tab": tab } : (headers ?? {});
}

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
    headers: withTab(
      init?.body instanceof FormData
        ? init?.headers
        : { "Content-Type": "application/json", ...init?.headers },
    ),
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
    let detail: string | { msg?: string }[] = response.statusText;
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      /* a non-JSON error body is still an error */
    }
    throw new ApiError(
      response.status,
      typeof detail === "string"
        ? detail
        : // FastAPI's 422 gives a list; its first message is readable ("at most 2000 characters").
          (detail[0]?.msg ?? "Request failed."),
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
  /** The kind of thinking the step asks for, 1 to 4: recall; apply or explain; justify or use
   * evidence; extended reasoning. `depth_set` is false when nobody chose it and it is the usual 2. */
  depth: number;
  depth_set: boolean;
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
  class_id: string;
  class_label: string;
  status: string;
  opened_at: string | null;
  closed_at: string | null;
  open_alerts: number;
  outcomes_to_confirm: number;
  /** In the lesson, wrote at least once, and finished every step. */
  students: number;
  took_part: number;
  finished: number;
};

/** What it takes to teach a lesson again from where it ended. */
export type TeachAgainInfo = {
  lesson_id: string;
  taught_class_id: string;
  classes: { id: string; label: string; students: number }[];
  /** The class of a lesson running now, if any: a teacher runs one at a time. */
  running: string | null;
};

export type LearnLine = {
  id: string;
  who: "student" | "agent" | "note";
  text: string;
  at: string;
  /** The student's one tap on an agent reply: it helped, or not really. Null until they say. */
  helped: boolean | null;
};

/** What the teacher confirmed. Nothing else about marks ever reaches a student. */
export type LearnResult = {
  total: number;
  out_of: number;
  criteria: { name: string; points: number; max: number }[];
  comment: string | null;
  /** The note the teacher confirmed: one thing done well, and what to look at again. */
  keep: string;
  develop: string[];
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
  /** What help the rules allow right now: a worked step in n more tries (0 means now), the
   * answer likewise, or never (null). */
  help: {
    hint: boolean;
    worked_step_in: number | null;
    answer_in: number | null;
    /** Help comes one kind at a time, each after another try (a study's fixed ladder). */
    ladder: boolean;
  };
  disclosure: string;
  result: LearnResult | null;
  /** Wrote or pressed a help button at least once; an opening alone is not taking part. */
  took_part: boolean;
  /** Their Ask my teacher is still open, until the teacher presses Dealt with. */
  asked_teacher: boolean;
  /** Wrong tries on the current step: after one, the help buttons change. */
  wrong_tries: number;
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
    /** The steps where the depth they showed was under the step's target, in one line. */
    depth?: string;
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
    /** The questions the agent asks on this step, in the teacher's words. */
    questions: string[];
    criteria: string[];
    has_reference: boolean;
    /** The answer the teacher's card shows; students never see it. */
    answer: string | null;
    depth: BriefStep["depth"];
    depth_set: BriefStep["depth_set"];
  }[];
  /** Words the teacher wants used and heard back, and how to adjust for this class; empty when
   * they said nothing about them. */
  key_terms: string[];
  support: string;
  /** What the agent filled in itself rather than from the teacher's words, as short names
   * ("objectives", "step 2 criteria", "depth targets", "rules"), until approval clears them. */
  to_check: string[];
  assessment: { name: string; max: number; description: string }[];
  rules_text: string;
  rules_in_words: string[];
  /** The same rules as short labels for the card's pills: the help, what interrupts the
   * teacher at once (with how many times it must happen), what is kept, their notes. */
  help: {
    pills: string[];
    at_once: { signal: string; words: string; after: number }[];
    kept: string[];
    notes: string[];
  };
  /** Wrong tries before a worked step, and whether hints are allowed at all. */
  worked_step_after: number;
  hints_allowed: boolean;
  missing: string[];
  study: boolean;
  approved_lesson_id: string | null;
  /** The unit this lesson is part of, by name, and every unit name the teacher has used. */
  unit: string | null;
  units: string[];
  /** How it is taught, for a side-by-side comparison: "direct", "inquiry" or nothing. */
  approach: string | null;
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
    unit: string | null;
    approach: string | null;
    status: "draft" | "active" | "closed";
    steps: number;
    duration_minutes: number;
    ready: boolean;
    live: LessonRun | null;
    last_run: LessonRun | null;
    /** An approved version exists, so a draft on top of it is a change to approve. */
    approved: boolean;
    /** When the lesson was first made: the order inside a unit. */
    created_at: string | null;
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
  /** Once it has ended: starting the same lesson with a class from here. */
  teach_again: TeachAgainInfo | null;
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
  /** What still needs the teacher about this student. */
  alerts: { id: string; kind: string; summary: string }[];
  /** Everyone in the lesson, to go straight to any of them. */
  classmates: { student_id: string; pseudonym: string; state: StudentState["state"] }[];
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
  /** The lesson has a mark scheme, so the notes carry suggested points too. */
  marked: boolean;
  /** Alerts still open after the lesson ended, so they are not lost. */
  alerts: LiveAlert[];
  teach_again: TeachAgainInfo | null;
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
      action:
        | "show_lesson"
        | "focus_lesson"
        | "approve"
        | "delete_lesson"
        // One model call: how step 1 would open for a student, written into the chat.
        | "preview_lesson";
      lesson_id: string;
    }
  | { action: "set_unit"; lesson_id: string; text: string }
  | { action: "set_approach"; lesson_id: string; text: string }
  | { action: "start_approach"; text: string }
  | { action: "copy_with_approach"; lesson_id: string; text: string }
  | { action: "delete_material"; material_id: string }
  | { action: "follow_up"; text: string }
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
  | { action: "acknowledge"; exception_id: string; student_id?: string };

/** The counts every research page shares, for a lesson, a student or the whole study. */
export type ResearchTally = {
  turns: number;
  mean_latency_ms: number;
  hints: number;
  worked_steps: number;
  /** Replies that stated the answer and reached the student. */
  answers_given: number;
  checks_failed: number;
  checks_fixed: number;
  held_back: number;
  alerts: number;
  alerts_dealt_with: number;
  /** Alerts the platform closed itself because the student moved on. */
  alerts_cleared: number;
  /** Still waiting for the teacher. */
  alerts_open: number;
  /** The students' own taps on replies. */
  helped: number;
  not_helped: number;
};

export type ResearchLessonRow = ResearchTally & {
  session_id: string;
  at: string | null;
  closed_at: string | null;
  title: string;
  subject: string;
  unit: string | null;
  teacher: string;
  class_label: string;
  status: string;
  condition: string;
  approach: string;
  students: number;
  took_part: number;
  finished: number;
  models: string[];
  prompt_versions: string[];
};

/** One group of students side by side with the others: a study condition, or a teaching approach. */
export type ResearchGroupRow = {
  name: string;
  lessons: number;
  students: number;
  finished: number;
  turns_per_student: number;
  help_per_student: number;
  answers_given: number;
  checks_failed: number;
  alerts: number;
  helped: number;
  not_helped: number;
  mean_mark_percent: number | null;
};

export type ResearchOverview = {
  study: {
    active: boolean;
    policy: string;
    supervisor: boolean;
    model: string;
    prompt_versions: string[];
  };
  totals: ResearchTally & { lessons: number; students: number; finished: number };
  conditions: ResearchGroupRow[];
  approaches: ResearchGroupRow[];
  lessons: ResearchLessonRow[];
};

export type ResearchStudentRow = {
  student_id: string;
  pseudonym: string;
  condition: string;
  took_part: boolean;
  finished: boolean;
  step_index: number;
  steps_total: number;
  judgments: (string | null)[];
  turns: number;
  hints: number;
  worked_steps: number;
  answers_given: number;
  checks_failed: number;
  helped: number;
  not_helped: number;
  check_kinds: string[];
  guided: number;
  alerts: {
    kind: string;
    at: string | null;
    status: string;
    dealt_with_at: string | null;
    because: string | null;
  }[];
  mark_suggested: number | null;
  mark_confirmed: number | null;
  needs_look: boolean;
};

export type ResearchLesson = Omit<ResearchLessonRow, "students"> & {
  steps: string[];
  mark_max: number;
  rules: string[];
  students: ResearchStudentRow[];
  alert_list: {
    id: string;
    at: string | null;
    kind: string;
    student_id: string;
    pseudonym: string;
    summary: string;
    status: string;
    dealt_with_at: string | null;
    /** Why the platform cleared it without the teacher, when it did. */
    because: string | null;
  }[];
  checks: {
    at: string | null;
    student_id: string;
    pseudonym: string;
    step_index: number | null;
    conflicts: string[];
    outcome: string;
    retried_because: string | null;
  }[];
  guidance: {
    at: string | null;
    student_id: string;
    pseudonym: string;
    text: string;
    shown_to_student: boolean;
  }[];
};

/** What one agent turn did, read from its reply and the server's checks. */
export type TurnFacts = {
  step_index: number | null;
  disclosure: string;
  allowed: string | null;
  hint: boolean;
  worked_step: boolean;
  answer: boolean;
  leaked: boolean;
  judgment: string | null;
  step_done: boolean;
  signals: { kind: string; told: boolean }[];
  conflicts: string[];
  outcome: string;
  retried_because: string | null;
  guided: boolean;
  /** The student wrote or pressed a help button: the turns help is counted on. */
  answered: boolean;
  latency_ms: number;
};

export type ConversationItem =
  | { kind: "student"; at: string | null; text: string }
  | { kind: "event"; at: string | null; text: string; teacher_only: boolean }
  | ({
      kind: "agent";
      at: string | null;
      text: string;
      withheld: boolean;
      turn_id: string | null;
      shown: Record<string, unknown> | null;
      raw: unknown;
      helped?: boolean | null;
    } & Partial<TurnFacts>);

export type ResearchConversation = {
  session_id: string;
  student_id: string;
  pseudonym: string;
  title: string;
  at: string | null;
  condition: string;
  approach: string;
  turns: number;
  models: string[];
  prompt_versions: string[];
  mean_latency_ms: number;
  steps: { name: string; judgment: string | null; attempts: number; reached: boolean }[];
  rules: string[];
  earlier: { title: string; at: string | null }[];
  memory_used: boolean;
  teacher: {
    at: string | null;
    what: "alert" | "dealt_with" | "cleared" | "guidance" | "read_conversation" | "mark";
    kind?: string;
    text?: string;
    shown_to_student?: boolean;
    total?: number | null;
    comment?: string | null;
  }[];
  mark: { suggested: number | null; confirmed: number | null; max: number; comment: string | null };
  previous: { student_id: string; pseudonym: string } | null;
  next: { student_id: string; pseudonym: string } | null;
  items: ConversationItem[];
};

export type Instructions = {
  teacher: string;
  student: string;
  review: string;
  /** What the agent is told under each teaching approach, while drafting and while teaching. */
  approaches: {
    version: string;
    held_constant: string;
    items: Record<string, { name: string; drafting: string; teaching: string; rules: Record<string, unknown> }>;
  };
};

export type ResearchTurn = {
  id: string;
  at: string;
  mode: "student" | "teacher" | "review" | string;
  student: string | null;
  /** For a teacher's turn, whose conversation it was. */
  teacher: string | null;
  said: string | null;
  button: string | null;
  error: string | null;
  retried_because?: string | null;
  shown: Record<string, unknown>;
  reply: Record<string, unknown> | string;
  prompts: string;
  model: string;
  latency_ms: number;
  outcome: string;
  leakage: string;
  conflicts: string[];
};

export type ResearchTurns = {
  session_id: string | null;
  lesson: string | null;
  turns: ResearchTurn[];
};

/** Signed in, no key is needed; the key still opens the view for someone who isn't. */
function researchHeaders(key: string): Record<string, string> {
  return key ? { "X-Research-Key": key } : {};
}

export const researchApi = {
  summary: (key: string) =>
    request<ResearchOverview>("/api/research/summary", {
      headers: researchHeaders(key),
    }),
  lesson: (key: string, sessionId: string) =>
    request<ResearchLesson>(`/api/research/lessons/${sessionId}`, {
      headers: researchHeaders(key),
    }),
  conversation: (key: string, sessionId: string, studentId: string) =>
    request<ResearchConversation>(
      `/api/research/lessons/${sessionId}/students/${studentId}`,
      { headers: researchHeaders(key) },
    ),
  instructions: (key: string) =>
    request<Instructions>("/api/research/instructions", {
      headers: researchHeaders(key),
    }),
  // Every model call of one lesson run, or with no run the teachers' conversations.
  turns: (key: string, sessionId?: string) =>
    request<ResearchTurns>(
      `/api/research/turns${sessionId ? `?session_id=${sessionId}` : ""}`,
      { headers: researchHeaders(key) },
    ),
  // The records as a zip of CSV files, handed to the browser as a download.
  download: async (key: string, withText: boolean) => {
    const response = await fetch(
      `${BASE}/api/research/export?with_text=${withText}`,
      {
        headers: withTab(researchHeaders(key)),
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

  // One tap on an agent reply: it helped, or not really.
  learnHelped: (sessionId: string, lineId: string, helped: boolean) =>
    request<Learn>(`/api/learn/${sessionId}/lines/${lineId}/helped`, post({ helped })),
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

  classProgress: (classId: string) =>
    request<ClassProgress>(`/api/teacher/classes/${classId}/progress`),

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

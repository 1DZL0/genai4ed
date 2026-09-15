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
  closes_at: string | null;
  items: number;
};

export type HistoryLine = {
  kind: "attempt" | "hint" | "teacher" | "ask";
  text: string;
  correct: boolean | null;
  at: string;
};

export type ItemKind = "short_answer" | "written_response";

export type Criterion = { name: string; max: number; description?: string };

/** A score the teacher has confirmed. Students never see a suggestion. */
export type ConfirmedScore = {
  total: number;
  out_of: number;
  criteria: { name: string; points: number; max: number }[];
  keep: string;
  develop: string[];
  comment: string | null;
};

export type Item = {
  id: string;
  ordinal: number;
  kind: ItemKind;
  prompt: string;
  attempts: number;
  solved: boolean;
  history: HistoryLine[];
  text: string;
  submitted: boolean;
  score: ConfirmedScore | null;
  rubric: Criterion[];
};

export type StudentSession = {
  session_id: string;
  status: string;
  closes_at: string | null;
  title: string;
  subject: string;
  material_notes: string | null;
  disclosure: string;
  phase_name: string | null;
  tutors_on: boolean;
  items: Item[];
  teacher_messages: HistoryLine[];
};

export type TutorAsk = "stuck" | "language" | "feedback" | "question";

export type HelpReply = { message: string; withheld: boolean; teacher_notified: boolean };

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
  kind: ItemKind;
  attempts: number;
  solved: boolean;
  rung: string | null;
  words: number;
  submitted: boolean;
  score: number | null;
  score_out_of: number | null;
  score_confirmed: boolean;
};

export type StudentProgress = {
  student_id: string;
  pseudonym: string;
  attempted: number;
  correct: number;
  attempts: number;
  needs_you: boolean;
  times_needed_you: number;
  cells: RegisterCell[];
};

export type Phase = { name: string; minutes: number; tutors_on: boolean };

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
  phase_name: string | null;
  tutors_on: boolean;
  students: number;
  items: number;
  open_exceptions: number;
  scores_to_confirm: number;
};

export type Today = { coming_up: LessonSummary[]; finished: LessonSummary[] };

export type ScoreCriterion = { name: string; points: number; max: number; reason?: string };

export type Score = {
  id: string;
  student_id: string;
  pseudonym: string;
  item_id: string;
  item_ordinal: number;
  prompt: string;
  text: string;
  status: "suggested" | "confirmed";
  out_of: number;
  suggested: { criteria: ScoreCriterion[]; keep: string; develop: string[] };
  suggested_total: number;
  confirmed: { criteria: ScoreCriterion[]; keep: string; develop: string[] } | null;
  confirmed_total: number | null;
  comment: string | null;
};

export type Review = {
  lesson: LessonSummary;
  item_list: { id: string; ordinal: number; prompt: string; kind: ItemKind }[];
  rungs: string[];
  students: number;
  started: number;
  finished_all: number;
  correct_answers: number;
  times_needed_you: number;
  progress: StudentProgress[];
};

export type TimelineEvent = {
  at: string;
  kind: string;
  item_ordinal: number | null;
  text: string;
  correct: boolean | null;
  rung: string | null;
};

export type StudentWork = {
  student_id: string;
  pseudonym: string;
  progress: StudentProgress;
  written: {
    item_id: string;
    ordinal: number;
    prompt: string;
    text: string;
    submitted: boolean;
    score: Score | null;
  }[];
  events: TimelineEvent[];
};

export type CastMember = {
  student_id: string;
  pseudonym: string;
  profile: string;
  description: string;
};

export type Walkthrough = {
  lesson_id: string;
  plan_version_id: string;
  class_label: string;
  writing_phase: number;
  cast: CastMember[];
};

export type PlanSummary = {
  id: string;
  plan_id: string;
  title: string;
  subject: string;
  status: string;
  version: number;
  items: number;
  max_rung: string;
  allow_full_solution: boolean;
  minutes: number;
  approved_version_id: string | null;
  approved_version: number | null;
  used_with: string[];
  archived: boolean;
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
  closes_at: string | null;
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
  kind?: ItemKind;
  prompt: string;
  expected_answer: string | null;
  rubric?: { criteria: Criterion[] } | null;
  hint_templates: Partial<Record<Rung, string>>;
  misconception_vocabulary: MisconceptionIn[];
};

export type ContractIn = {
  title: string;
  subject: string;
  objective_code: string;
  objective_title: string;
  max_rung: Rung;
  allow_full_solution: boolean;
  repeated_incorrect: number;
  repeated_misconception: number;
  confidence_floor: number;
  notes: string;
  timeline: Phase[];
  items: ItemIn[];
};

export type PlanDetail = PlanSummary & {
  objective_code: string;
  objective_title: string;
  notes: string;
  repeated_incorrect: number;
  repeated_misconception: number;
  confidence_floor: number;
  timeline: Phase[];
  item_list: ItemIn[];
};

export type Console = {
  session_id: string;
  status: string;
  closes_at: string | null;
  title: string;
  subject: string;
  class_label: string;
  items: number;
  item_list: { id: string; ordinal: number; prompt: string; kind: ItemKind }[];
  rungs: string[];
  timeline: Phase[];
  phase_index: number;
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

export const agentApi = {
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

  mySessions: () => request<SessionSummary[]>("/api/sessions"),

  studentSession: (id: string) => request<StudentSession>(`/api/sessions/${id}`),

  submitAttempt: (id: string, itemId: string, answer: string) =>
    request<AttemptResult>(`/api/sessions/${id}/attempts`, post({ item_id: itemId, answer })),

  requestTeacher: (id: string) =>
    request<{ status: string }>(`/api/sessions/${id}/request-teacher`, post()),

  saveDraft: (id: string, itemId: string, text: string) =>
    request<void>(`/api/sessions/${id}/items/${itemId}/draft`, {
      method: "PUT",
      body: JSON.stringify({ text }),
    }),

  askTutor: (id: string, itemId: string, ask: TutorAsk, text: string, question = "") =>
    request<HelpReply>(`/api/sessions/${id}/items/${itemId}/ask`, post({ ask, text, question })),

  submitWritten: (id: string, itemId: string, text: string) =>
    request<{ submitted: boolean; waiting_for_teacher: boolean }>(
      `/api/sessions/${id}/items/${itemId}/submit`,
      post({ text }),
    ),

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

  plans: () => request<PlanSummary[]>("/api/teacher/plans"),

  createPlan: (body: ContractIn) => request<PlanSummary>("/api/teacher/plans", post(body)),

  approvePlan: (id: string) => request<PlanSummary>(`/api/teacher/plans/${id}/approve`, post()),

  plan: (id: string) => request<PlanDetail>(`/api/teacher/plans/${id}`),

  updatePlan: (id: string, body: ContractIn) =>
    request<PlanSummary>(`/api/teacher/plans/${id}`, { method: "PUT", body: JSON.stringify(body) }),

  newPlanVersion: (id: string) =>
    request<PlanSummary>(`/api/teacher/plans/${id}/versions`, post()),

  duplicatePlan: (id: string) =>
    request<PlanSummary>(`/api/teacher/plans/${id}/duplicate`, post()),

  deletePlan: (id: string) =>
    request<{ outcome: "deleted" | "archived"; plan_id: string }>(`/api/teacher/plans/${id}`, {
      method: "DELETE",
    }),

  restorePlan: (id: string) => request<PlanSummary>(`/api/teacher/plans/${id}/restore`, post()),

  today: () => request<Today>("/api/teacher/today"),

  bookLesson: (planVersionId: string, classId: string, scheduledFor?: string) =>
    request<LessonSummary>(
      "/api/teacher/lessons",
      post({ plan_version_id: planVersionId, class_id: classId, scheduled_for: scheduledFor }),
    ),

  startLesson: (id: string) => request<LessonSummary>(`/api/teacher/lessons/${id}/start`, post()),

  changePhase: (id: string, index: number) =>
    request<LessonSummary>(`/api/teacher/lessons/${id}/phase`, post({ index })),

  pastLessons: () => request<LessonSummary[]>("/api/teacher/lessons/past"),

  review: (lessonId: string) => request<Review>(`/api/teacher/lessons/${lessonId}/review`),

  studentWork: (lessonId: string, studentId: string) =>
    request<StudentWork>(`/api/teacher/lessons/${lessonId}/students/${studentId}`),

  scores: (lessonId: string) => request<Score[]>(`/api/teacher/lessons/${lessonId}/scores`),

  confirmScore: (scoreId: string, points: Record<string, number>, comment: string) =>
    request<Score>(
      `/api/teacher/scores/${scoreId}/confirm`,
      post({ points, comment: comment.trim() || null }),
    ),

  teacherSessions: () => request<TeacherSessionSummary[]>("/api/teacher/sessions"),

  beginWalkthrough: () => request<Walkthrough>("/api/demo/walkthrough", post()),

  simulate: (lessonId: string, action: "start_writing" | "get_stuck" | "hand_in") =>
    request<{ happened: string[] }>(`/api/demo/lessons/${lessonId}/simulate`, post({ action })),

  walkthroughCast: (lessonId: string) =>
    request<CastMember[]>(`/api/demo/lessons/${lessonId}/cast`),

  walkthroughStudentView: (lessonId: string, studentId: string) =>
    request<StudentSession>(`/api/demo/lessons/${lessonId}/students/${studentId}/view`),

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

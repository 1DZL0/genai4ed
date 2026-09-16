-- Scratch queries for looking at what the platform recorded.
--
-- Plain SQL, so any client runs it. In VS Code with the PostgreSQL extension
-- (ms-ossdata.vscode-pgsql), open this file, pick the genai4ed connection, and
-- use the Run button; or select a single statement and run just that.
-- Connection: postgresql://genai4ed:genai4ed@127.0.0.1:5433/genai4ed
--
-- The data these read is fake: `app.seed`, demo sign-in and the walkthrough
-- write sample lessons and pretend students. Real content must come from a teacher.

-- What the teacher approved: each lesson brief, and the rules it compiled.
select title,
       status,
       version,
       brief -> 'duration_minutes'                           as minutes,
       jsonb_array_length(brief -> 'steps')                  as steps,
       brief -> 'rules' -> 'full_answer_after_attempts'      as answer_after,
       brief -> 'rules' -> 'escalations'                     as escalations
from lesson_contracts
order by created_at;

-- A student's conversation with the class agent. Change the pseudonym.
select m.created_at, m.role, m.audience, m.text, m.data -> 'move' as move
from messages m
join conversations c on c.id = m.conversation_id
join users u on u.id = c.student_id
where c.kind = 'student' and u.pseudonym = '9B-01'
order by m.created_at;

-- The evidence ledger, newest last: judgments, signals, rule events, guidance.
select e.created_at,
       u.pseudonym,
       e.kind,
       e.payload ->> 'judgment' as judgment,
       e.payload ->> 'signal'   as signal,
       e.payload ->> 'action'   as triage,
       e.payload ->> 'note'     as note,
       e.retention_class,
       e.purge_after
from evidence_records e
join users u on u.id = e.student_id
order by e.created_at;

-- Rule compliance: every agent call, what it was shown, and what the checks did.
-- A 'withheld' row is a reply that never reached a student.
select created_at,
       mode,
       validation_outcome,
       leakage_check,
       conflicts,
       jsonb_array_length(coalesce(context_manifest -> 'message_ids', '[]')) as messages_shown,
       context_manifest -> 'retrieved_used'                                  as used_past_lessons,
       latency_ms,
       provider,
       model
from agent_turns
order by created_at;

-- The feasibility metrics from concept note S5, in one query.
select count(*)                                                  as turns,
       count(*) filter (where validation_outcome = 'regenerated') as regenerated,
       count(*) filter (where validation_outcome = 'withheld')    as withheld,
       count(*) filter (where leakage_check = 'failed')           as answer_leaks,
       round(avg(latency_ms))                                     as avg_latency_ms,
       max(latency_ms)                                            as worst_latency_ms
from agent_turns
where mode = 'student';

-- What reached the teacher, in the order they would see it.
select e.priority,
       e.kind,
       u.pseudonym,
       e.status,
       e.summary,
       jsonb_array_length(e.supporting_record_ids) as citations
from exceptions e
join users u on u.id = e.student_id
order by e.priority, e.created_at;

-- Who looked at whose work. The promise made to students, kept as a table.
select l.created_at, t.pseudonym as teacher, s.pseudonym as student, l.action, l.detail
from teacher_access_log l
join users t on t.id = l.teacher_id
left join users s on s.id = l.student_id
order by l.created_at;

-- Proof of the pseudonymity claim: there is no name column to select.
select column_name, data_type from information_schema.columns
where table_name = 'users';

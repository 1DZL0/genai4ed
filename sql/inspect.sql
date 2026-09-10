-- Scratch queries for looking at what the platform recorded.
--
-- Plain SQL, so any client runs it. In VS Code with the PostgreSQL extension
-- (ms-ossdata.vscode-pgsql), open this file, pick the genai4ed connection, and
-- use the Run button; or select a single statement and run just that.
-- Connection: postgresql://genai4ed:genai4ed@127.0.0.1:5433/genai4ed
--
-- The data these read is fake. `app.seed` writes a stand-in lesson and
-- `app.demo` plays a lesson through it. Real content must come from a teacher.

-- What the teacher authored: the ladder and the thresholds she approved.
select title,
       status,
       assistance_ladder -> 'max_rung'            as ceiling,
       assistance_ladder -> 'allow_full_solution' as full_solution_allowed,
       exception_thresholds
from lesson_contracts;

-- Her items, with the closed misconception vocabulary the tutor must diagnose from.
select ordinal,
       prompt,
       expected_answer,
       jsonb_array_length(misconception_vocabulary) as misconceptions,
       jsonb_object_keys(hint_templates)            as rung_with_a_template
from contract_items
order by ordinal;

-- The evidence ledger, newest last. This is the only durable memory there is.
select created_at,
       kind,
       correct,
       attempt_index,
       payload,
       retention_class,
       purge_after
from evidence_records
order by created_at;

-- Policy compliance: permitted rung vs the rung actually used.
-- Every row where these differ was caught by the Supervisor, not shown to a student.
select created_at,
       rung_permitted,
       rung_used,
       validation_outcome,
       leakage_check,
       conflicts,
       latency_ms,
       provider,
       model
from tutor_turns
order by created_at;

-- The feasibility metrics from concept note S5, in one query.
select count(*)                                                as turns,
       count(*) filter (where validation_outcome = 'withheld') as withheld,
       count(*) filter (where leakage_check = 'failed')        as answer_leaks,
       count(*) filter (where jsonb_array_length(conflicts) > 0) as policy_conflicts,
       round(avg(latency_ms))                                  as avg_latency_ms,
       max(latency_ms)                                         as worst_latency_ms
from tutor_turns;

-- The teacher's queue, in the order she would see it.
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

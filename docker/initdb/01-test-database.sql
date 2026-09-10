-- Runs once, when the container's data volume is first created.
-- The compose file makes `genai4ed`; pytest needs its own database beside it.
create database genai4ed_test owner genai4ed;

-- This server exists only to serve this project, but lock the databases to
-- their owner anyway: it is the posture the pilot will need, and it costs
-- nothing to have it true from the start.
revoke connect on database genai4ed      from public;
revoke connect on database genai4ed_test from public;
grant  connect on database genai4ed      to genai4ed;
grant  connect on database genai4ed_test to genai4ed;

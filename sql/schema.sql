-- The whole schema in one grid: every column of every table, with its keys.
-- Run it against the genai4ed connection from either VS Code extension, or from a terminal:
--   docker exec -i genai4ed-db psql -U genai4ed -d genai4ed < sql/schema.sql
--
-- For the same view with what each field holds (the comments in models.py), use
--   docker exec genai4ed-api .venv/bin/python -m app.schema
-- or open docs/schema.md.
select c.table_name,
       c.ordinal_position                                   as n,
       c.column_name,
       case c.data_type
         when 'character varying'       then 'varchar(' || c.character_maximum_length || ')'
         when 'timestamp with time zone' then 'timestamptz'
         else c.data_type
       end                                                  as type,
       c.is_nullable = 'YES'                                as may_be_empty,
       string_agg(distinct case tc.constraint_type
                             when 'PRIMARY KEY' then 'PK'
                             when 'UNIQUE'      then 'unique'
                             when 'FOREIGN KEY' then '-> ' || ccu.table_name || '.' || ccu.column_name
                           end, ', ')                       as keys
from information_schema.columns c
left join information_schema.key_column_usage kcu
       on kcu.table_schema = c.table_schema
      and kcu.table_name   = c.table_name
      and kcu.column_name  = c.column_name
left join information_schema.table_constraints tc
       on tc.constraint_schema = kcu.constraint_schema
      and tc.constraint_name   = kcu.constraint_name
left join information_schema.constraint_column_usage ccu
       on ccu.constraint_schema = tc.constraint_schema
      and ccu.constraint_name   = tc.constraint_name
      and tc.constraint_type    = 'FOREIGN KEY'
where c.table_schema = 'public'
  and c.table_name <> 'alembic_version'
group by c.table_name, c.ordinal_position, c.column_name,
         c.data_type, c.character_maximum_length, c.is_nullable
order by c.table_name, c.ordinal_position;

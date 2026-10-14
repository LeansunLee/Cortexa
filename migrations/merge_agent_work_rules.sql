-- Approved: replace behavior/boundaries with work_rules, including version snapshots.
-- Back up t_agents and t_agent_versions before applying. Run with ON_ERROR_STOP.
BEGIN;
SET LOCAL lock_timeout = '10s';
LOCK TABLE t_agents, t_agent_versions IN ACCESS EXCLUSIVE MODE;

CREATE OR REPLACE FUNCTION pg_temp.merge_agent_work_rules(execution text, boundary text)
RETURNS text LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE
    WHEN execution IS NULL THEN boundary
    WHEN boundary IS NULL OR execution = boundary THEN execution
    ELSE '执行方式' || chr(10) || execution || chr(10) || chr(10) || '工作边界' || chr(10) || boundary
  END
  FROM (SELECT nullif(regexp_replace(execution, '^[[:space:]]+|[[:space:]]+$', '', 'g'), '') AS execution,
               nullif(regexp_replace(boundary, '^[[:space:]]+|[[:space:]]+$', '', 'g'), '') AS boundary) normalized
$$;

DO $$
DECLARE
  old_count integer;
  new_count integer;
BEGIN
  SELECT count(*) FILTER (WHERE column_name IN ('behavior', 'boundaries')),
         count(*) FILTER (WHERE column_name = 'work_rules')
    INTO old_count, new_count
    FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = 't_agents';
  IF old_count = 2 AND new_count = 0 THEN
    ALTER TABLE t_agents RENAME COLUMN boundaries TO work_rules;
    UPDATE t_agents SET work_rules = pg_temp.merge_agent_work_rules(behavior, work_rules);
    ALTER TABLE t_agents DROP COLUMN behavior;
  ELSIF old_count <> 0 OR new_count <> 1 THEN
    RAISE EXCEPTION 'Unexpected Agent instruction schema; migration rolled back';
  END IF;
END $$;
COMMENT ON COLUMN t_agents.work_rules IS '工作规则，定义执行流程、协作方式、能力边界及需要确认的操作';

UPDATE t_agent_versions
SET snapshot = (snapshot::jsonb - 'behavior' - 'boundaries') || jsonb_build_object(
  'work_rules', CASE WHEN snapshot::jsonb ? 'work_rules' THEN snapshot::jsonb -> 'work_rules'
                    ELSE to_jsonb(pg_temp.merge_agent_work_rules(snapshot ->> 'behavior', snapshot ->> 'boundaries')) END)
WHERE snapshot::jsonb ? 'behavior' OR snapshot::jsonb ? 'boundaries' OR NOT snapshot::jsonb ? 'work_rules';
COMMIT;

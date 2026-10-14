import pytest
from cortexa.agents.rules import merge_work_rules
from cortexa.agents.prompts import build_system_prompt
from cortexa.api.agents import _build_system_prompt as agent_test_prompt
from cortexa.api.meetings import _build_agent_meeting_prompt, _build_host_summary_prompt
from cortexa.api.schemas import AgentCreate, AgentUpdate, AgentOut
from cortexa.db.models import Agent


@pytest.mark.parametrize(('behavior', 'boundaries', 'expected'), [
    (None, None, None), ('  ', '', None), ('先查数据', None, '先查数据'),
    (None, '  不编造  ', '不编造'), ('同一规则', '同一规则', '同一规则'),
    ('先查数据', '不编造', '执行方式\n先查数据\n\n工作边界\n不编造'),
])
def test_merge_preserves_legacy_instructions(behavior, boundaries, expected):
    assert merge_work_rules(behavior, boundaries) == expected


def test_api_uses_single_field_and_accepts_legacy_payload_without_loss():
    for schema in (AgentCreate, AgentUpdate, AgentOut):
        fields = schema.model_json_schema()['properties']
        assert 'work_rules' in fields
        assert 'behavior' not in fields and 'boundaries' not in fields
    payload = AgentCreate(name='Peter', behavior='先查数据', boundaries='不编造')
    assert payload.work_rules == '执行方式\n先查数据\n\n工作边界\n不编造'
    assert AgentUpdate(work_rules=None, boundaries='旧值').model_dump(exclude_unset=True) == {'work_rules': None}
    assert AgentUpdate(name='改名').model_dump(exclude_unset=True) == {'name': '改名'}
    assert set(Agent.__table__.columns.keys()).isdisjoint({'behavior', 'boundaries'})


def test_work_rules_reach_chat_test_and_meeting_prompts():
    rules = '先核实数据；缺失时邀请具备查询能力的 Agent；不得编造实绩。'
    agent = Agent(name='Peter', role='营销负责人', work_rules=rules)
    for prompt in (build_system_prompt(agent), agent_test_prompt(agent),
                   _build_agent_meeting_prompt(agent, '制定销售计划', 'analysis'),
                   _build_host_summary_prompt(agent, '制定销售计划', 1, 2)):
        assert '工作规则' in prompt
        assert rules in prompt


def test_postgres_migration_preserves_rows_versions_and_is_repeatable():
    import os
    import uuid
    from pathlib import Path
    import psycopg
    from psycopg import sql
    from psycopg.types.json import Json
    url = os.getenv('WORK_RULES_TEST_DATABASE_URL')
    if not url:
        pytest.skip('Requires an isolated PostgreSQL database')
    schema = 'work_rules_' + uuid.uuid4().hex
    migration = (Path(__file__).parents[1] / 'migrations/merge_agent_work_rules.sql').read_text()
    samples = [(None, None), ('先查询，再协作', '不编造'), ('仅执行方式', None),
               (None, '仅边界'), ('相同规则', '相同规则'), ('  ', '  '), ('\n先查数据\t', '\n不编造\r\n'), ('\n\t', None)]
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("SET client_encoding TO UTF8")
        conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        try:
            conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
            conn.execute('CREATE TABLE t_agents (id int, behavior text, boundaries text, status text)')
            conn.execute('CREATE TABLE t_agent_versions (id int, snapshot json, is_published boolean)')
            for i, (execution, boundary) in enumerate(samples):
                conn.execute('INSERT INTO t_agents VALUES (%s,%s,%s,%s)', (i, execution, boundary, 'active'))
                conn.execute('INSERT INTO t_agent_versions VALUES (%s,%s,true)',
                             (i, Json({'behavior': execution, 'boundaries': boundary, 'name': 'Peter'})))
            for _ in range(2):
                conn.execute(migration)
                columns = {r[0] for r in conn.execute('SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s', (schema, 't_agents'))}
                assert 'work_rules' in columns and not columns & {'behavior', 'boundaries'}
                for i, rules, status in conn.execute('SELECT id,work_rules,status FROM t_agents ORDER BY id'):
                    assert rules == merge_work_rules(*samples[i])
                    assert status == 'active'
                for i, snapshot, published in conn.execute('SELECT * FROM t_agent_versions ORDER BY id'):
                    assert snapshot == {'name': 'Peter', 'work_rules': merge_work_rules(*samples[i])}
                    assert published
        finally:
            conn.execute('ROLLBACK')
            conn.execute('SET search_path TO public')
            conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))

"""Seed the web_research skill into every workspace and bind it to search-enabled agents.

正文取自 web_search.SEARCH_RULES（技能化后 meetings 等路径技能优先、该常量兜底）。
幂等：已有同名技能的工作空间跳过（--force 时更新正文并补绑定）。
"""
import argparse
import asyncio

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import select

from cortexa.db.engine import async_session_factory
from cortexa.db.models import Agent, Workspace
from cortexa.tools.skills import create_skill, update_skill
from cortexa.tools.web_search import SEARCH_RULES, search_enabled

DESCRIPTION = (
    "需要公开信息、最新消息，或用户明确要求联网/搜索时使用；"
    "按说明调用 web_search 并遵守关键词与引用约束。内部资料查询不适用本技能。"
)


async def main(force: bool = False):
    async with async_session_factory() as db:
        workspaces = list((await db.execute(select(Workspace))).scalars())
        created, updated, bound = 0, 0, 0
        for workspace in workspaces:
            from cortexa.tools.skills import list_skills
            existing = next((s for s in await list_skills(db, workspace.id) if s.name == "web_research"), None)
            if existing is None:
                record = await create_skill(
                    db, workspace.id, name="web_research", description=DESCRIPTION,
                    instructions=SEARCH_RULES.strip(),
                )
                created += 1
            elif force:
                await update_skill(db, existing, name="web_research", description=DESCRIPTION,
                                   instructions=SEARCH_RULES.strip())
                record = existing
                updated += 1
            else:
                record = existing
            skill_key = str(record.id)
            agents = list((await db.execute(
                select(Agent).where(Agent.workspace_id == workspace.id, Agent.status == "active")
            )).scalars())
            for agent in agents:
                if not search_enabled(agent):
                    continue
                ids = [str(value) for value in (agent.skill_ids or [])]
                if skill_key not in ids:
                    ids.append(skill_key)
                    agent.skill_ids = ids
                    bound += 1
        await db.commit()
        print(f"workspaces={len(workspaces)} created={created} updated={updated} agents_bound={bound}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="更新已存在技能的正文/描述并补齐绑定")
    args = parser.parse_args()
    asyncio.run(main(force=args.force))

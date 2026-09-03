# Architecture

## Overview

This project is a LangGraph multi-agent system with:

- shared agent state
- a researcher agent with tool access
- a writer agent
- a supervisor agent for routing
- basic tool integrations

## Tools

- `search_web` for web search
- `retrieve` for simple in-memory RAG
- `execute_code` for restricted local execution

## Flow

1. `researcher` gathers facts with tools
2. `supervisor` decides the next step
3. `writer` drafts the output
4. the graph ends when the supervisor chooses finish

## Files

- `src/agentdevstu/workflow/schema.py`
- `src/agentdevstu/agents/agents.py`
- `src/agentdevstu/workflow/graph.py`
- `src/agentdevstu/tools/`
- `src/agentdevstu/cli.py`

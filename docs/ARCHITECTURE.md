# Architecture

> 历史架构说明：本文件描述早期 LangGraph/CLI 示例。当前 Web 平台架构、产品范围和实现边界请参见[产品设计说明书](PRODUCT_DESIGN_20260918.md)与[项目基线](PROJECT_BASELINE_20260916.md)。

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

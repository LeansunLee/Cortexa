from __future__ import annotations

import argparse

from cortexa.config.llm_providers import get_provider_config
from cortexa.config.settings import load_env
from cortexa.workflow.graph import build_graph


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the LangGraph multi-agent demo.")
    parser.add_argument("--goal", required=True, help="Task goal for the multi-agent team.")
    parser.add_argument("--max-iterations", type=int, default=4, help="Iteration cap.")
    parser.add_argument("--provider", default=None, help="Override LLM provider name.")
    return parser.parse_args()


def app() -> None:
    args = parse_args()
    load_env()

    try:
        pcfg = get_provider_config(args.provider)
        provider_label = f"{pcfg.kind}/{pcfg.model}"
    except Exception:
        provider_label = "local-fallback"

    graph = build_graph()
    print(f"[demo] provider={provider_label}")
    print(f"[demo] goal={args.goal}")

    result: dict[str, object] = graph.invoke(
        {
            "goal": args.goal,
            "iterations": 0,
            "max_iterations": args.max_iterations,
        }
    )

    print("\n=== FINAL DRAFT ===\n")
    print(result.get("draft", ""))
    print("\n=== NOTES ===\n")
    print(result.get("notes", ""))

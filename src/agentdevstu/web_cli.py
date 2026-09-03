from __future__ import annotations

import argparse

import uvicorn


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start AgentDevStu web server.")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host.")
    parser.add_argument("--port", type=int, default=8000, help="Bind port.")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload.")
    return parser.parse_args()


def app() -> None:
    args = parse_args()
    print("\n🚀 AgentDevStu Web Server")
    print(f"   http://localhost:{args.port}/       ← 配置页")
    print(f"   http://localhost:{args.port}/chat    ← 对话页\n")
    uvicorn.run(
        "agentdevstu.web.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )

"""Shared test configuration.

Windows默认 ProactorEventLoop 与 psycopg 异步模式不兼容，
统一切换到 SelectorEventLoop；Linux/macOS 不受影响。
"""

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

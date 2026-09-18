"""Dedicated SQLite runtime for SearXNG on CentOS 7; does not modify system Python."""
import sys
import pysqlite3

sys.modules['sqlite3'] = pysqlite3
from searx.webapp import app  # noqa: E402,F401

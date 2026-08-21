#!/usr/bin/env python
"""Prepare or upgrade the app_users authentication table.

The app still performs a defensive schema check at startup for backward
compatibility, but deployment automation should prefer this explicit migration
entrypoint.
"""
from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from services import user_store


def main() -> int:
    if not user_store.available():
        print('app_users table is not available. Check DATABASE_URL and database connectivity.', file=sys.stderr)
        return 1
    print('app_users table is ready.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

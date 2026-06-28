"""Shared MongoDB client. Imported by server.py and route modules.
Loading .env from server.py before this import ensures MONGO_URL is set.
"""
import os
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
# Typed as `Any` because Motor's bundled stubs declare `find_one` / collection
# accessors as returning `None`, which is incorrect at runtime and produces a
# wave of false-positive mypy errors. Until motor-stubs ships richer types,
# treating `db` as `Any` is the standard escape hatch.
db: Any = client[os.environ['DB_NAME']]

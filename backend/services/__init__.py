"""Shared service helpers extracted from server.py during iter33 refactor.

These modules contain pure business logic (rate math, transaction aggregation,
order workflow) that is consumed by multiple route files. Keeping them here
avoids circular imports between sibling routers.
"""

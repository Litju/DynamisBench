"""Optional transport primitives.

Nothing here is scientific authority and nothing here is imported by the scientific core or
by the application boundary at startup. A transport module is reached explicitly by the code
that needs it, which is also why the heavy libraries it wraps are imported inside functions.
"""

"""DEPRECATED module: kept to avoid breaking imports but no longer used.

The application ASGI app was moved to `vncrcc.app`. The `api` package
directory provides the route submodules under `vncrcc.api.v1` and this
module used to conflict with that package name. To avoid confusion the
server now uses `vncrcc.app:app` and this module is a marker that can be
deleted when you're confident no external tooling imports it.

If you see code importing `vncrcc.api` expecting the ASGI app, update it to
`vncrcc.app:app`.
"""

print("WARNING: src/vncrcc/api.py is deprecated. Use vncrcc.app for the ASGI app.")

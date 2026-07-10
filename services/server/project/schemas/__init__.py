"""Pydantic request schemas (transport-agnostic).

Used by the Flask routes and, later, the MCP tools to validate incoming
payloads before they reach a service. Response serialisation stays on the ORM
models (to_dict), so this package is request-side only.
"""

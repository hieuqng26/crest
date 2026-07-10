"""Application service layer.

Transport-agnostic orchestration shared by the Flask routes and (later) the MCP
server. Services may use the ORM, core computation, storage, and Celery
dispatch, but MUST NOT import ``flask`` or touch request/response objects —
auth and (de)serialisation stay in the caller (route or tool).
"""

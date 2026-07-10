"""crest_* tool modules. Each module registers its tools on import (see
``project.mcp_server.server``) and contains no logic beyond parse → service
call — the same thin-transport rule the Flask routes follow.

Outputs are JSON dicts (structured content); list/log/result tools are
paginated with hard caps so results stay within an agent's context budget.
"""

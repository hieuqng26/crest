---
name: debug-stack
description: >-
  Run, spin up, or verify a CREST BACKEND change against the real debug stack (MSSQL +
  Redis + MinIO) instead of only pytest. Use whenever the user wants to "spin up the
  debug stack", "test/verify this on the real stack", "confirm the endpoint works
  against the real DB", smoke-test a route on live infra, get a worktree/branch's
  backend running in docker, or exercise behaviour the SQLite tests can't cover
  (cookie/CSRF auth, MinIO artifacts, MSSQL, Celery, Alembic migrations). Covers
  building the worktree image and attaching it to the already-running stack, or
  standing up an isolated parallel stack for migration-bearing changes. NOT for pure
  frontend/Vite work, writing unit tests, plain docker-compose troubleshooting, or
  Playwright/UI testing (use webapp-testing for those). Note the trap it avoids: the
  running mst-* containers bake code into the image (source is NOT volume-mounted), so
  a restart won't pick up worktree edits — you must rebuild. Reach for this instead of
  saying you "can't run the live stack" — you usually can.
---

# Verifying a backend change on the CREST debug stack

## Why this skill exists

The dev stack (`docker-compose.debug.yml`) runs the Flask backend, Celery workers,
Redis, MSSQL, and MinIO. Two facts make "just test it live" trickier than it looks,
and this skill encodes the way around them:

1. **Code is baked into the image, not mounted.** The backend image (`mst-dev/backend:latest`)
   `COPY`s the source at build time; only a *data* volume is mounted. So editing files
   in your worktree and running `docker compose restart` changes **nothing** — the
   container still serves the old code. Verifying a change requires a **rebuild**.
2. **The image tag and host ports are shared and hardcoded.** Every service references
   the single tag `mst-dev/backend:latest`, and ports (backend 5001, MSSQL 1433, MinIO
   9100/9101) are fixed in the compose file. If you rebuild that tag or start a second
   copy naively, you either overwrite the running stack's image or collide on ports.

The default method below sidesteps both: build the worktree under a **distinct tag**
and run it as **one extra backend container attached to the already-running stack's
network**, reusing its MSSQL/Redis/MinIO on a **spare port**. Nothing about the running
`mst-*` stack changes; you just add (and later remove) a single container.

## Preflight (always do this first)

Confirm the environment before building anything:

```bash
docker ps --format '{{.Names}}\t{{.Status}}' | grep -i backend   # is a stack up?
docker network ls --format '{{.Name}}' | grep app-network        # which network(s)?
```

Then decide the method from what you find (see **Choosing a method**). If nothing is
running, either start the stack normally (`docker compose -f docker-compose.debug.yml
up -d`) or use the parallel/fresh method.

> **Migration guard — read before attaching.** The backend entrypoint runs
> `flask db upgrade` on startup. If your branch adds an Alembic migration, attaching to
> the *shared* dev DB will apply it to that real database. When the change carries a new
> migration (check `services/server/migrations/versions/`), do **not** use the attach
> method — use a **parallel stack** (own isolated DB) instead. For code-only changes
> (no new migration), attach is safe: `db upgrade` and `seed_db` are idempotent no-ops.

## Choosing a method

| Situation | Method |
|---|---|
| Stack already running, **code-only** change (no new migration) | **Attach** (default, below) — fastest, non-disruptive |
| Change adds a **migration**, or you want a clean DB | **Parallel stack** (isolated project + DB, remapped ports) |
| No stack running and you want the normal experience | **Fresh stack** (plain `docker compose ... up`, on the branch) |

## Method 1 — Attach to the running stack (default)

Build the worktree image under a distinct tag and run it as an extra backend on the
running stack's network. The bundled script does the whole dance (auto-detects the
network from the running backend container, locates the gitignored env file via
`git worktree list`, builds, runs, waits for `/api/ping`):

```bash
.claude/skills/debug-stack/scripts/attach-backend.sh
# → builds worktree-dev/backend:latest, starts container "worktree-verify-backend"
#   on the running stack's network, published at http://localhost:5002
```

Useful overrides (env vars): `PORT` (default 5002), `TAG`, `NAME`, `NETWORK`,
`ENVFILE`. Run `attach-backend.sh --help` for details.

What the container does on boot (from `services/server/entrypoint.sh`): waits for MSSQL,
ensures the DB/login exist, runs `flask db upgrade`, runs `manage.py seed_db` (seeds the
admin user), then starts the Flask dev server. All idempotent against the shared dev DB.

### Exercise the feature and read the result back

Auth is cookie-based with a CSRF double-submit token. The `api.sh` helper logs in with
the seeded admin (`SEED_ADMIN_EMAIL`/`SEED_ADMIN_PASSWORD` from the env file — `admin`/
`admin` in the default dev env), stores cookies, and sends the `X-CSRF-TOKEN` header on
writes for you:

```bash
API=.claude/skills/debug-stack/scripts/api.sh          # BASE defaults to :5002

$API login                                             # establishes the session
$API post /api/model-configs/ '{"name":"smoke","algorithm":"ElasticNet"}'
$API delete /api/datasets/999999                       # exercise a failure path
$API get  /api/model-configs/                          # a read
```

Then read the effect back through the API (or query the DB) to *observe* the behaviour —
don't just trust the 2xx. For example, to confirm audit rows or any listing endpoint,
call the relevant read endpoint and inspect the JSON.

> **Gotcha — `/api/log/all` pagination is 0-indexed.** It does `offset(page * page_size)`,
> so the most recent rows are on `page: 0`, not `page: 1`. Post
> `{"page":0,"page_size":25}` to see the latest entries.

### Clean up (leave the running stack exactly as you found it)

```bash
.claude/skills/debug-stack/scripts/cleanup.sh
# removes the worktree-verify-backend container + worktree-dev image; the mst-* stack
# is untouched. Any test rows you created remain in the dev DB (append-only, harmless) —
# delete them explicitly if you care.
```

If you created disposable entities during the test (e.g. a throwaway model config),
delete them via the API before teardown so the dev DB stays tidy.

## Method 2 — Parallel stack (isolated DB, own ports)

Use when the change adds a migration or you need a pristine database. Bring up a second
compose *project* (isolated network + volumes) with a distinct image tag and remapped
host ports so it can coexist with the running stack. See
[references/parallel-stack.md](references/parallel-stack.md) for the exact override file
and commands.

## Method 3 — Fresh stack on the branch

If no stack is running and you want the full normal setup (workers, beat, mcp, and the
option to point the Vite frontend at it), just build and start the compose stack from the
worktree:

```bash
docker compose -f docker-compose.debug.yml build backend
docker compose -f docker-compose.debug.yml up -d
```

This uses the default tag/ports, so only do it when no other CREST stack is up. Frontend
(separate from the compose stack) runs via `cd services/client && npm run dev` and reads
its API base from `services/client/.env`.

## Verify against real behaviour, not just green tests

The whole point of going live is to *observe* the change working against real infra.
Prefer proof over assertion: hit the endpoint, then read the resulting state back
(list/detail endpoint, DB row, MinIO object, job log). Report what you actually saw. The
pytest suite (SQLite, mocked Celery) is a fast first gate; the live stack is what proves
auth, MSSQL, MinIO, and migrations behave.

## Common failure signs

- **Container exits immediately / `debugpy ... --listen 0.0.0.0:` error** — `DEBUG_PORT`
  unset while `FLASK_DEBUG=1`. The attach script sets it; if running `docker run`
  manually, pass `-e DEBUG_PORT=5678`.
- **`/api/ping` never returns 200** — MSSQL wasn't reachable on the network, or the DB is
  still migrating. Check `docker logs <name>`; the entrypoint prints "Waiting for MSSQL".
- **Login 401 / seed missing** — `SEED_ADMIN_PASSWORD` not set in the env file (seeding
  raises `SystemExit`), or you're hitting the wrong port.
- **Port already allocated** — another stack owns your chosen host port; pick a free one
  via `PORT=5003 attach-backend.sh`.
```

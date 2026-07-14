# Method 2 — Parallel stack (isolated DB, remapped ports)

Use this when the change **adds a migration** or you otherwise need a pristine database
that is fully isolated from the running `mst-*` stack. It brings up a second Compose
*project* — its own network and its own MSSQL/MinIO data volumes (so a fresh, empty DB)
— with a distinct image tag and remapped host ports so nothing collides.

## 1. Override file (distinct image tag + remapped ports)

Write this next to `docker-compose.debug.yml` in the worktree root (it's an ephemeral
artifact — delete it after). A distinct `image:` tag means the build never overwrites the
running stack's `mst-dev/backend:latest`; the remapped ports avoid collisions.

```yaml
# docker-compose.todo-verify.yml
services:
  backend:
    image: worktree-dev/backend:latest
    build:
      context: services/server
      dockerfile: Dockerfile
    ports:
      - "5002:5000"
      - "5680:5678"
  mssql:
    ports:
      - "1434:1433"
  minio:
    ports:
      - "9102:9000"
      - "9103:9001"
```

Redis publishes no host port in the base file, so it needs no remap.

## 2. Build and bring up (isolated project name)

The `-p` project name isolates the network and volumes (they get prefixed with it, e.g.
`todo6e58e5_mssql_data`), giving you a clean DB. Only start what you need — `backend`
pulls in its `depends_on` (redis, mssql, minio) automatically; skip the workers unless
the feature needs Celery.

```bash
PROJ=todo6e58e5
docker compose -p "$PROJ" -f docker-compose.debug.yml -f docker-compose.todo-verify.yml build backend
docker compose -p "$PROJ" -f docker-compose.debug.yml -f docker-compose.todo-verify.yml up -d backend
```

The backend self-migrates (`flask db upgrade`, now against the fresh isolated DB) and
seeds the admin user on boot. Wait for `http://localhost:5002/api/ping` to return 200.

## 3. Exercise and verify

Same as the attach method — use `scripts/api.sh` (its `BASE` already defaults to `:5002`)
to log in and drive endpoints, then read the result back.

## 4. Tear down (removes the isolated DB too)

```bash
PROJ=todo6e58e5
docker compose -p "$PROJ" -f docker-compose.debug.yml -f docker-compose.todo-verify.yml down -v
docker image rm worktree-dev/backend:latest 2>/dev/null || true
rm -f docker-compose.todo-verify.yml
```

`down -v` also drops the isolated volumes, so no dev data lingers.

# Sopify-shipped Supabase Local

Minimal Supabase stack for Vibe Code projects. Started/stopped via the
`sopify supabase` subcommand (when wired) or directly with `docker compose`.

## Quick reference

```bash
# Bring up
docker compose -f docker/supabase/docker-compose.yaml up -d

# Tear down (keep the database volume)
docker compose -f docker/supabase/docker-compose.yaml down

# Tear down AND wipe data
docker compose -f docker/supabase/docker-compose.yaml down -v

# Logs (follow)
docker compose -f docker/supabase/docker-compose.yaml logs -f postgres
```

## Service map

| Service  | Host port | Container port | Purpose                      |
|----------|-----------|----------------|------------------------------|
| postgres | 5432      | 5432           | Raw Postgres (psql / drivers)|
| rest     | 54321     | 3000           | PostgREST — JS client target |
| auth     | 54320     | 9999           | GoTrue auth (JWT, signup)    |
| meta     | 54322     | 8080           | Postgres metadata REST       |
| studio   | 54323     | 3000           | Browser UI                   |

All bound to `127.0.0.1`. Open Studio: <http://127.0.0.1:54323>.

## From inside the Sopify sandbox

The agent inside the microVM reaches these via `host.docker.internal`:

| URL                                          | What                          |
|----------------------------------------------|-------------------------------|
| `http://host.docker.internal:54321`          | `VITE_SUPABASE_URL` for client|
| `http://host.docker.internal:54320`          | Auth API (signup / signin)    |
| `postgres://postgres:sopify-supabase-dev@host.docker.internal:5432/postgres` | `psql` / migrations |

## Credentials (DEV ONLY)

```
POSTGRES_USER:     postgres
POSTGRES_PASSWORD: sopify-supabase-dev
JWT_SECRET:        sopify-dev-jwt-secret-change-me-1234567890abcdef
```

Do **not** use these for anything outside a local dev box. The compose file
is a starting point — production-grade deployments need TLS, real secrets,
the realtime + storage-api services, and Kong as the unified API gateway.

# AgentForge backend

The backend is a FastAPI application using PostgreSQL as its durable data
store. SQLAlchemy 2.x models live in `app/agentforge/domain/models/`; Alembic
migrations live in `migrations/`.

## Requirements and environment

- Python 3.11–3.14
- [uv](https://docs.astral.sh/uv/)
- PostgreSQL 16 or newer (or Docker Desktop)

From the repository root, copy the environment template and set a local
password for PostgreSQL in `.env`. Use URL-encoded characters if the password
contains reserved URL characters.

```powershell
Copy-Item .env.example .env
python -m uv --directory backend sync --all-groups
```

`DATABASE_URL` is the application PostgreSQL connection string and
`TEST_DATABASE_URL` must refer to the separate `agentforge_test` database.
Both URLs must use the `postgresql+psycopg` SQLAlchemy driver. The test suite
refuses any test URL that is not local, does not target `agentforge_test`, or
matches the application URL. `APP_ENV=test` selects `TEST_DATABASE_URL` for
the application and migration commands.

Authentication has not been specified for this single-operator MVP, so the
`users` table intentionally has no password field. Do not expose this service
to an untrusted network without an approved authentication mechanism.

## Start the local database

The supplied Compose service binds PostgreSQL to loopback only and creates
both `agentforge` and `agentforge_test` databases on first initialization.
Run from the repository root after setting `POSTGRES_PASSWORD` in `.env`:

```powershell
docker compose --env-file .env -f backend/docker-compose.yml up -d db
docker compose --env-file .env -f backend/docker-compose.yml ps
```

If a PostgreSQL instance is already available, create an isolated test
database named `agentforge_test` owned by the application role. Do not point
the test URL at the development or production database.

## Migrations

Run all database commands from the repository root. Alembic loads its
connection URL from application settings and imports the model metadata for
autogeneration.

```powershell
python -m uv --directory backend run alembic upgrade head
python -m uv --directory backend run alembic current
```

Create a migration after changing the SQLAlchemy models, then review and apply
it:

```powershell
python -m uv --directory backend run alembic revision --autogenerate -m "describe schema change"
python -m uv --directory backend run alembic upgrade head
```

Rollback one migration with:

```powershell
python -m uv --directory backend run alembic downgrade -1
```

To apply or roll back migrations against the isolated test database, select
test mode first:

```powershell
$env:APP_ENV = "test"
python -m uv --directory backend run alembic upgrade head
Remove-Item Env:APP_ENV
```

## Tests and checks

The database integration tests use PostgreSQL features including UUID and
JSONB, so they do not substitute SQLite. They migrate and clean up only the
database named `agentforge_test`. Set test mode and execute:

```powershell
$env:APP_ENV = "test"
python -m uv --directory backend run pytest
python -m uv --directory backend run ruff check app tests migrations
Remove-Item Env:APP_ENV
```

The API liveness endpoint does not require the database. Request handlers can
inject a request-scoped SQLAlchemy `Session` with
`agentforge.database.dependencies.get_db_session`; its transaction is rolled
back when left uncommitted.

## Run the API

```powershell
python -m uv --directory backend run uvicorn agentforge.main:app --reload
```

The API listens at `http://127.0.0.1:8000`. Configure secrets only in local
environment variables or an untracked `.env`; never commit credentials or
include them in logs.

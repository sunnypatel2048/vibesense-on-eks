# ADR-0014: Schema migrations as an Argo CD Sync hook

**Status:** Accepted

## Context

Several services share the database, and pods must never run against a schema they don't expect.

## Decision

Alembic is the only schema owner. The chart runs `alembic upgrade head` as a Job that is an Argo CD **Sync** hook in wave 0: after the wave −1 ExternalSecrets (so its database URL exists) and before the Deployments in wave 1. Every service checks at startup that the database is at the expected revision and refuses to start otherwise.

## Consequences

- A failed migration fails the sync, so new pods never roll out onto a schema they can't use.
- The plan said PreSync; that would run before the ExternalSecrets exist, so on a fresh cluster the Job would wait forever for its Secret.
- The engine is built from the URL directly, because Alembic's ConfigParser treats the `%` in a URL-encoded password as interpolation.

## Alternatives considered

`create_all()` at service startup (no migrations, races between services); a PreSync hook (see above); an init container per Deployment (every pod runs migrations).

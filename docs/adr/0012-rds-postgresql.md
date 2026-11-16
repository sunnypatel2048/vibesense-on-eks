# ADR-0012: RDS PostgreSQL, single-AZ, smallest Graviton instance

**Status:** Accepted

## Context

Jobs and interval results need a relational store with a unique constraint for idempotency.

## Decision

RDS PostgreSQL 16 on `db.t4g.micro`, 20 GB gp3, single-AZ, in subnets with no internet route, reachable only from the node security group. RDS manages the master password in Secrets Manager; connections use `sslmode=require`. No final snapshot and no deletion protection, so `make down` can delete it.

## Consequences

- Managed patching and backups, about $0.016/hour.
- Single-AZ: no automatic failover. Deletion protection off: one command deletes the data, which is right for a demo and wrong for production (both recorded in `docs/security.md`).

## Alternatives considered

PostgreSQL in the cluster (a stateful workload to operate, lost on every teardown); Aurora Serverless v2 (higher minimum cost); DynamoDB (the existing relational model and migrations would be rewritten).

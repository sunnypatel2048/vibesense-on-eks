# ADR-0004: Graviton (arm64) and Spot capacity

**Status:** Accepted

## Context

Compute is the largest variable cost, and every node is disposable.

## Decision

All nodes are arm64 (Graviton) Spot instances, in several instance families so Spot capacity rarely runs out. Images are built for `linux/arm64` only: natively on an Apple Silicon Mac, and on GitHub's free arm64 runners in CI.

## Consequences

- Cheaper per vCPU than x86, and Spot is cheaper again.
- Spot can be reclaimed with 2 minutes' notice: Karpenter handles interruption events from an SQS queue, and the workers survive a drain without losing messages (measured: all AI pods Ready again 74 s after a drain, 200/200 messages processed).
- Every dependency must ship arm64 wheels or images (PyTorch's CPU build does).

## Alternatives considered

x86 on-demand (simpler, costs more); a mixed-architecture cluster (multi-arch images double CI build time for no benefit here).

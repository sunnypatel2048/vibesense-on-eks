# ADR-0010: KEDA on queue depth; the AI worker scales to zero on its own node pool

**Status:** Accepted

## Context

Load is bursty: nothing for hours, then a batch of comments. The AI worker is the heaviest workload (the model in memory, the largest image), and idle replicas still hold a node.

## Decision

KEDA scales each worker on its SQS queue's depth, counting in-flight messages (AI 0–6 pods at 5 messages per pod; the others 1–3). Autoscaled Deployments have no `replicas` field, so Argo CD never fights KEDA. The AI worker runs only on Karpenter's tainted `burst` NodePool (Graviton Spot, medium to xlarge, 16-vCPU cap, consolidation after 1 minute).

## Consequences

- Measured: 200 messages processed in 202 s from zero AI pods; pods back to 0 after 159 s and burst nodes removed after 315 s.
- Scale-from-zero costs a cold start (87 s measured: node, image pull, model load), which shaped the SLO target (ADR-0011).
- KEDA reads queue attributes with its own role (`sqs:GetQueueAttributes` only), never the messages.

## Alternatives considered

Horizontal Pod Autoscaler on CPU (a worker waiting on the YouTube API shows low CPU while its backlog grows); a warm minimum of one AI pod (faster, costs a node around the clock).

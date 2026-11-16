# Architecture decision records

Why VibeSense is built the way it is. Each record states the context, the
decision, its consequences, and the alternatives that were rejected and why.
Format: [Michael Nygard's ADR template](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions).

| ADR | Decision |
| --- | --- |
| [0001](0001-sqs-instead-of-rabbitmq-celery.md) | SQS queues with dead-letter queues instead of RabbitMQ and Celery |
| [0002](0002-eventbridge-scheduler-per-job.md) | EventBridge Scheduler for each job's interval schedule |
| [0003](0003-eks-with-karpenter.md) | EKS with a small managed node group, plus Karpenter for burst capacity |
| [0004](0004-graviton-and-spot.md) | Graviton (arm64) and Spot capacity |
| [0005](0005-public-subnets-no-nat.md) | Public subnets with no NAT gateway |
| [0006](0006-two-terraform-layers.md) | Terraform in two layers with separate state |
| [0007](0007-argo-cd-app-of-apps.md) | Argo CD app-of-apps for everything inside the cluster |
| [0008](0008-secrets-in-ssm-via-external-secrets.md) | Secrets in SSM Parameter Store, synced by External Secrets, never in Terraform |
| [0009](0009-pod-identity-per-workload.md) | EKS Pod Identity with one IAM role per workload |
| [0010](0010-keda-queue-depth-scale-to-zero.md) | KEDA on queue depth; the AI worker scales to zero on its own node pool |
| [0011](0011-observability-and-slo.md) | In-cluster Prometheus and Grafana, and a 5-minute latency SLO |
| [0012](0012-rds-postgresql.md) | RDS PostgreSQL, single-AZ, smallest Graviton instance |
| [0013](0013-model-baked-into-image.md) | The model is baked into the image, with a golden output check |
| [0014](0014-migrations-as-sync-hook.md) | Schema migrations as an Argo CD Sync hook |
| [0015](0015-gmail-smtp.md) | Gmail SMTP for reports, Amazon SES deferred |
| [0016](0016-gitops-bridge.md) | GitOps Bridge: Terraform outputs reach Argo CD through the cluster record |
| [0017](0017-webhook-certs-from-cert-manager.md) | Admission webhook certificates from cert-manager, not from chart rendering |
| [0018](0018-at-least-once-idempotent-writes.md) | At-least-once delivery with idempotent writes |
| [0019](0019-ci-oidc-no-apply-role.md) | CI with OIDC, no apply role, and pinned actions |

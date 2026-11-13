# Platform layer

Everything `make up` creates and `make down` destroys: network, EKS, RDS, SQS,
EventBridge Scheduler and per-workload IAM. It shares the bootstrap layer's
state bucket under its own key, and looks up bootstrap resources by name.

```bash
cd infra/platform
terraform init -backend-config=../bootstrap/backend.hcl   # once per clone
terraform plan
terraform apply
terraform destroy      # at the end of every session
```

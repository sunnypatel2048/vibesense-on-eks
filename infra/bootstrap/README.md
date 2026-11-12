# Bootstrap layer

Persistent AWS resources that outlive every `make down`: the Terraform state
bucket now, and later ECR repositories, CI roles, SSM parameters and the budget.

## First-time setup (the state bucket bootstraps itself)

The state bucket can't hold its own state before it exists, so it's created with
local state first, then the state is moved into it.

```bash
cd infra/bootstrap
terraform init
terraform apply                    # creates the bucket; state is local for now

# Write backend.hcl BEFORE adding backend.tf: once a backend block exists,
# Terraform won't run `terraform output` until the backend is initialized.
cat > backend.hcl <<EOT
bucket = "$(terraform output -raw state_bucket)"
region = "us-east-1"
EOT

# Now add backend.tf (backend "s3" with key + use_lockfile), then:
cp terraform.tfstate ~/bootstrap-state-backup.json
terraform init -backend-config=backend.hcl -migrate-state   # answer yes
terraform plan                                              # must say "No changes."
rm terraform.tfstate terraform.tfstate.backup
```

## Day to day

```bash
terraform init -backend-config=backend.hcl   # once per clone
terraform plan
terraform apply
```

`backend.hcl` is gitignored because it contains the AWS account ID.

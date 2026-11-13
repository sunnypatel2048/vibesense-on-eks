# tflint for every layer under infra/: `make lint-infra`.
# After changing a plugin version, run `tflint --init --config infra/.tflint.hcl`.

config {
  call_module_type = "local" # also lint our own modules (infra/modules, Phase 4)
}

# Terraform language rules: unused declarations, version constraints, naming, ...
plugin "terraform" {
  enabled = true
  preset  = "recommended"
}

# AWS-specific rules: invalid instance types, deprecated arguments, ...
plugin "aws" {
  enabled = true
  version = "0.43.0"
  source  = "github.com/terraform-linters/tflint-ruleset-aws"
}

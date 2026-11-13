# GitHub Actions authenticates to AWS with short-lived OIDC credentials instead of
# stored access keys. Each role trusts tokens only from this repository AND only
# from specific refs/events: checking the audience alone would let ANY GitHub
# repository assume the role, since GitHub signs tokens for everyone.

locals {
  github_oidc_host = "token.actions.githubusercontent.com"
  repo_sub_prefix  = "repo:${var.github_repository}"
}

# AWS verifies GitHub's tokens against its own trusted CAs, so no thumbprint is needed.
resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://${local.github_oidc_host}"
  client_id_list = ["sts.amazonaws.com"]
}

# Trust policy shared by both roles; `subjects` decides where a job may run.
data "aws_iam_policy_document" "github_trust" {
  for_each = {
    push = ["${local.repo_sub_prefix}:ref:refs/heads/main"]
    plan = [
      "${local.repo_sub_prefix}:pull_request",          # terraform plan on PRs
      "${local.repo_sub_prefix}:ref:refs/heads/main",   # nightly leftovers check (Task 10.4)
    ]
  }

  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.github_oidc_host}:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Exact matches only; no wildcards.
    condition {
      test     = "StringEquals"
      variable = "${local.github_oidc_host}:sub"
      values   = each.value
    }
  }
}

# --- Push role: merges to main build and push images ----------------------------

resource "aws_iam_role" "ci_push" {
  name                 = "${var.project}-ci-push"
  description          = "GitHub Actions on main: push images to ECR."
  assume_role_policy   = data.aws_iam_policy_document.github_trust["push"].json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "ci_push" {
  statement {
    sid       = "EcrLogin"
    actions   = ["ecr:GetAuthorizationToken"] # can't be scoped to a repository
    resources = ["*"]
  }

  statement {
    sid = "PushToVibesenseRepos"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:PutImage",
      "ecr:BatchGetImage",          # read back for layer caching
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [for repo in aws_ecr_repository.image : repo.arn]
  }
}

resource "aws_iam_role_policy" "ci_push" {
  name   = "push-images"
  role   = aws_iam_role.ci_push.id
  policy = data.aws_iam_policy_document.ci_push.json
}

# --- Plan role: PRs run terraform plan; no apply role exists ----------------------

resource "aws_iam_role" "ci_plan" {
  name                 = "${var.project}-ci-plan"
  description          = "GitHub Actions on PRs and nightly: read-only, for terraform plan."
  assume_role_policy   = data.aws_iam_policy_document.github_trust["plan"].json
  max_session_duration = 3600
}

# Broad read access: terraform plan refreshes every resource type it manages.
# Trade-off recorded in docs/security.md.
resource "aws_iam_role_policy_attachment" "ci_plan_read_only" {
  role       = aws_iam_role.ci_plan.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

# Even `plan` takes the state lock, which writes and deletes a .tflock object.
data "aws_iam_policy_document" "ci_plan_state_lock" {
  statement {
    sid       = "TerraformStateLock"
    actions   = ["s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.tfstate.arn}/*.tflock"]
  }
}

resource "aws_iam_role_policy" "ci_plan_state_lock" {
  name   = "terraform-state-lock"
  role   = aws_iam_role.ci_plan.id
  policy = data.aws_iam_policy_document.ci_plan_state_lock.json
}

# ReadOnlyAccess could otherwise decrypt the app's secrets. Terraform never
# manages them (scripts/put-secrets.sh does), so denying them breaks no plan.
# An explicit deny always overrides an allow.
data "aws_iam_policy_document" "ci_plan_deny_secrets" {
  statement {
    sid    = "DenyAppSecrets"
    effect = "Deny"
    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters",
      "ssm:GetParameterHistory", # returns earlier values too
    ]
    resources = [
      "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter/${var.project}/secrets/*",
    ]
  }

  # A by-path read of a parent path (e.g. "/" recursively) would return the
  # secrets too. Terraform here reads parameters by name, so deny it outright.
  statement {
    sid       = "DenyReadByPath"
    effect    = "Deny"
    actions   = ["ssm:GetParametersByPath"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "ci_plan_deny_secrets" {
  name   = "deny-app-secrets"
  role   = aws_iam_role.ci_plan.id
  policy = data.aws_iam_policy_document.ci_plan_deny_secrets.json
}

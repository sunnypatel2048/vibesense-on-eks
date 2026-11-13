# One least-privilege IAM role per workload, via EKS Pod Identity (ADR 9).
# A compromised pod can do only what its own role allows.
# The Load Balancer Controller and Karpenter roles use their projects' published
# policies and are added with those components (Tasks 5.4 and 8.3).

locals {
  queue_arn = { for stage, q in module.queue : stage => q.arn }

  # Receive/delete/backoff on one queue. The *Batch calls (used to release
  # messages on shutdown) are authorized by these same actions.
  consume_actions = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:ChangeMessageVisibility", "sqs:GetQueueUrl"]
  send_actions    = ["sqs:SendMessage", "sqs:GetQueueUrl"]

  # Each pipeline worker consumes one queue and (except the last) sends to the next.
  pipeline = {
    ingestion    = { consumes = "ingest", sends = "analysis" }
    ai           = { consumes = "analysis", sends = "aggregation" }
    aggregation  = { consumes = "aggregation", sends = "notification" }
    notification = { consumes = "notification", sends = null }
  }

  ssm_arn_prefix = "arn:aws:ssm:${var.region}:${local.account_id}:parameter/${var.project}"
}

# --- Pipeline workers ----------------------------------------------------------

data "aws_iam_policy_document" "pipeline" {
  for_each = local.pipeline

  statement {
    sid       = "Consume"
    actions   = local.consume_actions
    resources = [local.queue_arn[each.value.consumes]]
  }

  dynamic "statement" {
    for_each = each.value.sends == null ? [] : [each.value.sends]
    content {
      sid       = "SendToNextStage"
      actions   = local.send_actions
      resources = [local.queue_arn[statement.value]]
    }
  }
}

module "pipeline_role" {
  source   = "../modules/workload-role"
  for_each = local.pipeline

  name            = "${var.project}-${each.key}"
  cluster_name    = module.eks.cluster_name
  cluster_arn     = module.eks.cluster_arn
  namespace       = var.project
  service_account = each.key
  policy_json     = data.aws_iam_policy_document.pipeline[each.key].json
}

# --- UI: creates one schedule per job ------------------------------------------

data "aws_iam_policy_document" "ui" {
  statement {
    sid       = "ManageJobSchedules"
    actions   = ["scheduler:CreateSchedule", "scheduler:DeleteSchedule"] # all the app calls
    resources = ["arn:aws:scheduler:${var.region}:${local.account_id}:schedule/${aws_scheduler_schedule_group.jobs.name}/*"]
  }

  # Creating a schedule names the role Scheduler will use. Without this limit a
  # compromised UI could pass ANY role to Scheduler: privilege escalation.
  statement {
    sid       = "PassOnlyTheSchedulerRole"
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.scheduler.arn]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["scheduler.amazonaws.com"]
    }
  }

  statement {
    sid       = "KickOffFirstIngest"
    actions   = local.send_actions
    resources = [local.queue_arn["ingest"]]
  }
}

module "ui_role" {
  source = "../modules/workload-role"

  name            = "${var.project}-ui"
  cluster_name    = module.eks.cluster_name
  cluster_arn     = module.eks.cluster_arn
  namespace       = var.project
  service_account = "ui"
  policy_json     = data.aws_iam_policy_document.ui.json
}

# --- External Secrets Operator: syncs SSM / Secrets Manager into the cluster ---

data "aws_iam_policy_document" "external_secrets" {
  statement {
    sid     = "ReadAppConfigAndSecrets"
    actions = ["ssm:GetParameter", "ssm:GetParameters"]
    resources = [
      "${local.ssm_arn_prefix}/secrets/*",  # put there by `make secrets`
      "${local.ssm_arn_prefix}/platform/*", # written by Terraform (Task 4.8)
    ]
  }

  statement {
    sid       = "ReadDatabasePassword"
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = [aws_db_instance.main.master_user_secret[0].secret_arn]
  }
}

module "external_secrets_role" {
  source = "../modules/workload-role"

  name            = "${var.project}-external-secrets"
  cluster_name    = module.eks.cluster_name
  cluster_arn     = module.eks.cluster_arn
  namespace       = "external-secrets"
  service_account = "external-secrets"
  policy_json     = data.aws_iam_policy_document.external_secrets.json
}

# --- KEDA: scales workers on queue depth ----------------------------------------

data "aws_iam_policy_document" "keda" {
  statement {
    sid       = "ReadQueueDepth"
    actions   = ["sqs:GetQueueAttributes"] # message counts only; never the messages
    resources = values(local.queue_arn)
  }
}

module "keda_role" {
  source = "../modules/workload-role"

  name            = "${var.project}-keda-operator"
  cluster_name    = module.eks.cluster_name
  cluster_arn     = module.eks.cluster_arn
  namespace       = "keda"
  service_account = "keda-operator"
  policy_json     = data.aws_iam_policy_document.keda.json
}

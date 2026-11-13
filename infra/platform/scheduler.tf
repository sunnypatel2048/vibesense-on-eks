# EventBridge Scheduler: the UI creates one schedule per monitoring job in this
# group (src/common/scheduler.py). Each run puts {job_id, post_id} on the ingest queue.

# Deleting a group deletes the schedules in it, so `terraform destroy` also
# removes schedules the app created at runtime, which Terraform never knew about.
resource "aws_scheduler_schedule_group" "jobs" {
  name = var.project # matches SchedulerSettings.schedule_group
}

locals {
  account_id = data.aws_caller_identity.current.account_id
}

# Scheduler assumes this role to deliver each run's message. The conditions
# prevent the "confused deputy" problem: without them, any AWS account could
# create a schedule naming this role and have Scheduler send into our queue.
data "aws_iam_policy_document" "scheduler_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = [aws_scheduler_schedule_group.jobs.arn]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${var.project}-scheduler"
  description        = "EventBridge Scheduler: deliver job runs to the ingest queue."
  assume_role_policy = data.aws_iam_policy_document.scheduler_trust.json
}

data "aws_iam_policy_document" "scheduler_send" {
  statement {
    sid       = "SendToIngestQueue"
    actions   = ["sqs:SendMessage"]
    resources = [module.queue["ingest"].arn]
  }
}

resource "aws_iam_role_policy" "scheduler_send" {
  name   = "send-to-ingest-queue"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler_send.json
}

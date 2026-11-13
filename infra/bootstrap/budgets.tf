# The two budgets created by hand in Task 0.3, adopted into Terraform with
# import blocks (config first generated with `terraform plan -generate-config-out`,
# then tidied). Both track unblended cost with default charge types.

import {
  to = aws_budgets_budget.monthly
  id = "${data.aws_caller_identity.current.account_id}:vibesense-monthly"
}

import {
  to = aws_budgets_budget.daily
  id = "${data.aws_caller_identity.current.account_id}:vibesense-daily"
}

# Month-level guardrail: early warnings at 50% and 80%, plus a forecast alert so
# a cluster left running is caught before the month's total is spent.
resource "aws_budgets_budget" "monthly" {
  name         = "vibesense-monthly"
  budget_type  = "COST"
  limit_amount = "10.0"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = [50, 80, 100]
    content {
      comparison_operator        = "GREATER_THAN"
      notification_type          = "ACTUAL"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      subscriber_email_addresses = [var.alerts_email]
    }
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    notification_type          = "FORECASTED"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    subscriber_email_addresses = [var.alerts_email]
  }

  # AWS records `metrics = ["UnblendedCost"]` on these budgets. Setting it here
  # requires a filter_expression too (provider validation), and omitting it
  # makes Terraform try to remove it. Leave AWS's value alone.
  lifecycle {
    ignore_changes = [metrics]
  }
}

# Day-level tripwire: a forgotten EKS cluster costs ~$5-6/day, so this emails
# within a day instead of after half the monthly budget is gone.
# (Daily budgets don't support forecasted alerts.)
resource "aws_budgets_budget" "daily" {
  name         = "vibesense-daily"
  budget_type  = "COST"
  limit_amount = "1.0"
  limit_unit   = "USD"
  time_unit    = "DAILY"

  notification {
    comparison_operator        = "GREATER_THAN"
    notification_type          = "ACTUAL"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    subscriber_email_addresses = [var.alerts_email]
  }

  # AWS records `metrics = ["UnblendedCost"]` on these budgets. Setting it here
  # requires a filter_expression too (provider validation), and omitting it
  # makes Terraform try to remove it. Leave AWS's value alone.
  lifecycle {
    ignore_changes = [metrics]
  }
}

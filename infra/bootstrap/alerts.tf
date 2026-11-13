# Alarm notifications. Lives in the bootstrap layer because an email
# subscription must be confirmed by clicking a link: in the ephemeral platform
# layer it would need re-confirming after every `make up`.
#
# Not KMS-encrypted: CloudWatch alarms can't publish to a topic encrypted with
# the AWS-managed aws/sns key, and a customer-managed key costs ~$1/month.
# Alarm messages contain nothing sensitive. See docs/security.md.
resource "aws_sns_topic" "alerts" {
  name = "${var.project}-alerts"
}

# AWS emails a confirmation link; the subscription stays "pending" until clicked.
resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alerts_email
}

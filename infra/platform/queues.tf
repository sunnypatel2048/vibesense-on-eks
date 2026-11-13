# One queue + DLQ + alarm per pipeline stage. Visibility timeouts match the
# local ElasticMQ config and each worker's health-check busy limit (Task 1.8).

locals {
  queues = {
    ingest       = 300 # a busy video can take many YouTube API pages
    analysis     = 300 # model inference on a large batch
    aggregation  = 60
    notification = 60
  }
}

# Looked up by name, not read from the bootstrap layer's state: the layers stay
# loosely coupled.
data "aws_sns_topic" "alerts" {
  name = "${var.project}-alerts"
}

module "queue" {
  source   = "../modules/sqs-with-dlq"
  for_each = local.queues

  name                       = "${var.project}-${each.key}"
  visibility_timeout_seconds = each.value
  alarm_topic_arn            = data.aws_sns_topic.alerts.arn
}

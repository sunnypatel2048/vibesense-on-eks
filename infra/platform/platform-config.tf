# Non-secret values that change on every `make up`, published for the cluster.
# Argo CD deploys from Git, which can't hold them; External Secrets copies them
# into a Kubernetes Secret. Real secrets live under /vibesense/secrets/.

locals {
  platform_config = {
    scheduler_role_arn = aws_iam_role.scheduler.arn # SCHEDULER_ROLE_ARN (UI)
    ingest_queue_arn   = module.queue["ingest"].arn # INGEST_QUEUE_ARN (UI)
    db_host            = aws_db_instance.main.address
    db_port            = tostring(aws_db_instance.main.port)
    db_name            = aws_db_instance.main.db_name
    # RDS names its managed secret randomly, anew on every create. How External
    # Secrets finds it: by name pattern (deploy/charts/vibesense/templates/external-secrets.yaml); published here for debugging.
    db_secret_arn = aws_db_instance.main.master_user_secret[0].secret_arn
    # Where Alertmanager sends the SLO alert: the same topic, and so
    # the same email, as the CloudWatch DLQ alarms.
    alerts_topic_arn = data.aws_sns_topic.alerts.arn
  }
}

resource "aws_ssm_parameter" "platform_config" {
  #checkov:skip=CKV2_AWS_34:Identifiers (ARNs, hostname, port), not secrets; plain text keeps them readable when debugging
  for_each = local.platform_config

  name  = "/${var.project}/platform/${each.key}"
  type  = "String"
  value = each.value
}

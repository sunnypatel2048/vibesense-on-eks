output "vpc_id" {
  value = module.vpc.vpc_id
}

output "availability_zone_ids" {
  value = var.availability_zone_ids
}

output "public_subnet_ids" {
  value = module.vpc.public_subnets
}

output "database_subnet_group" {
  value = module.vpc.database_subnet_group_name
}

output "cluster_name" {
  value = module.eks.cluster_name
}

output "kubeconfig_command" {
  description = "Run after apply to point kubectl at the cluster."
  value       = "aws eks update-kubeconfig --region ${var.region} --name ${module.eks.cluster_name}"
}

output "rds_endpoint" {
  value = aws_db_instance.main.address
}

output "rds_master_secret_arn" {
  description = "Secrets Manager secret (username/password JSON) that RDS manages."
  value       = aws_db_instance.main.master_user_secret[0].secret_arn
}

output "queue_urls" {
  value = { for stage, q in module.queue : stage => q.url }
}

output "queue_arns" {
  value = { for stage, q in module.queue : stage => q.arn }
}

output "schedule_group" {
  value = aws_scheduler_schedule_group.jobs.name
}

output "scheduler_role_arn" {
  description = "Role each schedule's target uses (SCHEDULER_ROLE_ARN in the UI)."
  value       = aws_iam_role.scheduler.arn
}

output "workload_role_arns" {
  value = merge(
    { for name, r in module.pipeline_role : name => r.role_arn },
    {
      ui               = module.ui_role.role_arn
      external-secrets = module.external_secrets_role.role_arn
      keda-operator    = module.keda_role.role_arn
    },
  )
}

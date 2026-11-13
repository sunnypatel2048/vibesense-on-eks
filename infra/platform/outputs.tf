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

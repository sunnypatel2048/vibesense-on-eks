# PostgreSQL for job and interval data. Single-AZ, smallest Graviton class:
# a demo database that is created and destroyed with the platform.

resource "aws_security_group" "rds" {
  name        = "${var.project}-rds"
  description = "PostgreSQL, reachable only from EKS nodes"
  vpc_id      = module.vpc.vpc_id
}

# Pods use their node's security group, so "only the nodes" means "only the cluster".
resource "aws_vpc_security_group_ingress_rule" "rds_from_nodes" {
  security_group_id            = aws_security_group.rds.id
  description                  = "PostgreSQL from EKS nodes"
  referenced_security_group_id = module.eks.node_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

resource "aws_db_instance" "main" {
  # Demo database, destroyed with the platform; production alternatives in docs/security.md.
  #checkov:skip=CKV_AWS_293:Deletion protection would make terraform destroy fail on every make down
  #checkov:skip=CKV_AWS_157:Multi-AZ doubles the cost for failover a demo does not need
  #checkov:skip=CKV_AWS_161:Password is RDS-generated and never handled by a person or Terraform; IAM auth needs per-connection tokens in the app
  #checkov:skip=CKV_AWS_129:Log exports are billed per GB and their log groups outlive the instance
  #checkov:skip=CKV2_AWS_30:Query logging needs log exports and would record user email addresses
  #checkov:skip=CKV_AWS_118:Enhanced monitoring needs an extra IAM role and bills through CloudWatch Logs
  #checkov:skip=CKV_AWS_353:Demo-scale database; application metrics go to Grafana (Phase 9)
  identifier = var.project

  engine            = "postgres"
  engine_version    = "16" # major only: RDS picks the latest 16.x; matches local compose
  instance_class    = "db.t4g.micro"
  allocated_storage = 20
  storage_type      = "gp3"
  storage_encrypted = true # AWS-managed aws/rds key: free, nothing lingers after destroy

  db_name  = var.project
  username = var.project
  # RDS generates the password and keeps it in Secrets Manager. Terraform never
  # sees it, so it can't end up in the state file. External Secrets reads it.
  manage_master_user_password = true

  db_subnet_group_name   = module.vpc.database_subnet_group_name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false
  multi_az               = false # failover isn't worth double the cost for a demo

  # TLS is required by default on PostgreSQL 15+ (rds.force_ssl = 1).
  auto_minor_version_upgrade = true
  apply_immediately          = true

  backup_retention_period  = 1    # free up to the database's size
  delete_automated_backups = true # backups go with the instance on destroy
  copy_tags_to_snapshot    = true

  # Teardown: a final snapshot would bill monthly after every `make down`, and
  # deletion protection would make `terraform destroy` fail. Production: invert both.
  skip_final_snapshot = true
  deletion_protection = false
}

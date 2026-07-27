# Single RDS PostgreSQL instance replacing the local `postgres` Compose
# service, which also hosts several logical databases on one Postgres
# process (omniflow_orders/omniflow_inventory/omniflow_orchestrator/
# omniflow_gateway/omniflow_failure_lab — see
# infra/docker/postgres/init-databases.sql). RDS creates exactly one
# database at instance-creation time; the rest are a documented manual
# post-provision step (README's "Post-provision manual step") — this
# module does not attempt a live psql connection from Terraform itself.

locals {
  name_prefix = "${var.project}-${var.environment}"
}

resource "aws_kms_key" "rds" {
  description         = "KMS key encrypting the ${local.name_prefix} RDS instance (storage + master-user secret) at rest."
  enable_key_rotation = true

  tags = merge(var.tags, {
    Name = "${local.name_prefix}-rds-kms"
  })
}

resource "aws_kms_alias" "rds" {
  name          = "alias/${local.name_prefix}-rds"
  target_key_id = aws_kms_key.rds.key_id
}

resource "aws_db_subnet_group" "this" {
  name       = "${local.name_prefix}-db-subnet-group"
  subnet_ids = var.private_subnet_ids

  tags = merge(var.tags, {
    Name = "${local.name_prefix}-db-subnet-group"
  })
}

resource "aws_db_parameter_group" "this" {
  name_prefix = "${local.name_prefix}-pg16-"
  family      = "postgres16"
  description = "Parameter group for ${local.name_prefix} — logs statements taking >1s, matching this project's 'observable by default' posture."

  parameter {
    name  = "log_min_duration_statement"
    value = "1000"
  }

  parameter {
    name  = "log_connections"
    value = "1"
  }

  lifecycle {
    create_before_destroy = true
  }

  tags = var.tags
}

resource "aws_iam_role" "rds_monitoring" {
  count = var.monitoring_interval_seconds > 0 ? 1 : 0
  name  = "${local.name_prefix}-rds-monitoring"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "monitoring.rds.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "rds_monitoring" {
  count      = var.monitoring_interval_seconds > 0 ? 1 : 0
  role       = aws_iam_role.rds_monitoring[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}

resource "aws_db_instance" "this" {
  identifier     = "${local.name_prefix}-postgres"
  engine         = "postgres"
  engine_version = var.engine_version

  instance_class        = var.instance_class
  allocated_storage     = var.allocated_storage_gb
  max_allocated_storage = var.max_allocated_storage_gb
  storage_type          = "gp3"
  storage_encrypted     = true
  kms_key_id            = aws_kms_key.rds.arn

  db_name  = var.database_name
  username = var.master_username
  password = var.master_password

  db_subnet_group_name   = aws_db_subnet_group.this.name
  parameter_group_name   = aws_db_parameter_group.this.name
  vpc_security_group_ids = [var.security_group_id]
  publicly_accessible    = false

  multi_az                  = var.multi_az
  backup_retention_period   = var.backup_retention_days
  backup_window             = "03:00-04:00"
  maintenance_window        = "mon:04:30-mon:05:30"
  copy_tags_to_snapshot     = true
  deletion_protection       = var.deletion_protection
  skip_final_snapshot       = false
  final_snapshot_identifier = "${local.name_prefix}-postgres-final"

  monitoring_interval = var.monitoring_interval_seconds
  monitoring_role_arn = var.monitoring_interval_seconds > 0 ? aws_iam_role.rds_monitoring[0].arn : null

  performance_insights_enabled    = var.performance_insights_enabled
  performance_insights_kms_key_id = var.performance_insights_enabled ? aws_kms_key.rds.arn : null

  auto_minor_version_upgrade = true
  apply_immediately          = false

  tags = merge(var.tags, {
    Name = "${local.name_prefix}-postgres"
  })
}

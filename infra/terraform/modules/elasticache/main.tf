# ElastiCache Redis — modeled for the concrete next step RISKS.md #13 names
# for horizontally scaling the API Gateway (a shared backing store for its
# in-process rate limiter and connection state), and for
# docs/architecture.md's own AWS deployment diagram, which already names
# ElastiCache Redis. Not yet consumed by any application code today — the
# gateway's rate limiter is still the documented single-instance in-process
# implementation (RISKS.md #13), so wiring an application to this resource
# is future work, not claimed as done here.

locals {
  name_prefix = "${var.project}-${var.environment}"
}

resource "aws_kms_key" "elasticache" {
  description         = "KMS key encrypting the ${local.name_prefix} ElastiCache Redis replication group at rest."
  enable_key_rotation = true

  tags = merge(var.tags, {
    Name = "${local.name_prefix}-elasticache-kms"
  })
}

resource "aws_kms_alias" "elasticache" {
  name          = "alias/${local.name_prefix}-elasticache"
  target_key_id = aws_kms_key.elasticache.key_id
}

resource "random_password" "redis_auth_token" {
  # Redis AUTH tokens: 16-128 printable ASCII chars, no "/", "@", '"', or space.
  length           = 40
  special          = true
  override_special = "!#$%^&*()-_=+"
}

resource "aws_secretsmanager_secret" "redis_auth_token" {
  name                    = "${local.name_prefix}/elasticache/auth-token"
  description             = "Redis AUTH token for the ${local.name_prefix} ElastiCache replication group (Terraform-generated)."
  kms_key_id              = aws_kms_key.elasticache.arn
  recovery_window_in_days = 7

  tags = merge(var.tags, {
    Name = "${local.name_prefix}-elasticache-auth-token"
  })
}

resource "aws_secretsmanager_secret_version" "redis_auth_token" {
  secret_id     = aws_secretsmanager_secret.redis_auth_token.id
  secret_string = random_password.redis_auth_token.result
}

resource "aws_elasticache_subnet_group" "this" {
  name       = "${local.name_prefix}-cache-subnet-group"
  subnet_ids = var.private_subnet_ids

  tags = var.tags
}

resource "aws_elasticache_replication_group" "this" {
  replication_group_id = "${local.name_prefix}-redis"
  description          = "Redis for ${local.name_prefix} — modeled for a future shared rate-limiter/cache backing store (RISKS.md #13), not yet consumed by application code."

  engine               = "redis"
  engine_version       = var.engine_version
  node_type            = var.node_type
  num_cache_clusters   = var.num_cache_clusters
  port                 = 6379
  parameter_group_name = "default.redis7"

  subnet_group_name  = aws_elasticache_subnet_group.this.name
  security_group_ids = [var.security_group_id]

  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  auth_token                 = random_password.redis_auth_token.result
  kms_key_id                 = aws_kms_key.elasticache.arn

  automatic_failover_enabled = var.automatic_failover_enabled
  multi_az_enabled           = var.automatic_failover_enabled && var.num_cache_clusters > 1

  snapshot_retention_limit = var.snapshot_retention_days
  snapshot_window          = "05:00-06:00"
  maintenance_window       = "mon:06:30-mon:07:30"

  auto_minor_version_upgrade = true
  apply_immediately          = false

  tags = merge(var.tags, {
    Name = "${local.name_prefix}-redis"
  })
}

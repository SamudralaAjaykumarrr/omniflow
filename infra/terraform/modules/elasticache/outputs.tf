output "primary_endpoint_address" {
  description = "Primary (writer) endpoint address for the Redis replication group."
  value       = aws_elasticache_replication_group.this.primary_endpoint_address
}

output "reader_endpoint_address" {
  description = "Reader endpoint address (only meaningful when num_cache_clusters > 1)."
  value       = aws_elasticache_replication_group.this.reader_endpoint_address
}

output "port" {
  description = "Redis port."
  value       = aws_elasticache_replication_group.this.port
}

output "auth_token_secret_arn" {
  description = "Secrets Manager ARN for the Redis AUTH token."
  value       = aws_secretsmanager_secret.redis_auth_token.arn
}

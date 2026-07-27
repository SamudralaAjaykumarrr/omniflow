output "identifier" {
  description = "RDS instance identifier (for CloudWatch dimension / alarm wiring)."
  value       = aws_db_instance.this.identifier
}

output "kms_key_arn" {
  description = "ARN of the KMS key encrypting this RDS instance."
  value       = aws_kms_key.rds.arn
}

output "endpoint" {
  description = "RDS instance connection endpoint (host:port). No password included."
  value       = aws_db_instance.this.endpoint
}

output "address" {
  description = "RDS instance hostname only (no port)."
  value       = aws_db_instance.this.address
}

output "port" {
  description = "RDS instance port."
  value       = aws_db_instance.this.port
}

output "master_username" {
  description = "RDS master username (password is a separate sensitive input — see modules/secrets' rds_master_password output and its own Secrets Manager secret)."
  value       = aws_db_instance.this.username
}

output "database_name" {
  description = "Name of the single database RDS created at instance-creation time — see README for the remaining per-service databases' manual bootstrap step."
  value       = aws_db_instance.this.db_name
}

output "resource_id" {
  description = "RDS resource ID (used for IAM database authentication policy ARNs, if ever enabled)."
  value       = aws_db_instance.this.resource_id
}

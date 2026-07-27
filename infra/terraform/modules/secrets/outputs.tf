output "rds_master_password" {
  description = "Plaintext RDS master password (sensitive) — used only by the environment root config to compose per-service DATABASE_URL secrets. Never logged, never written to a plain output; Terraform still records it in state (see README's state-handling note)."
  value       = random_password.rds_master.result
  sensitive   = true
}

output "rds_master_password_secret_arn" {
  description = "Secrets Manager ARN for the RDS master password on its own (for direct psql access, e.g. the documented post-provision database-bootstrap step)."
  value       = aws_secretsmanager_secret.rds_master_password.arn
}

output "jwt_secret_key_secret_arn" {
  description = "Secrets Manager ARN for the shared JWT signing secret."
  value       = aws_secretsmanager_secret.jwt_secret_key.arn
}

output "seed_password_secret_arns" {
  description = "Map of seed account name (admin/ops/viewer/service) -> Secrets Manager ARN."
  value       = { for name, secret in aws_secretsmanager_secret.seed_password : name => secret.arn }
}

output "kms_key_arn" {
  description = "ARN of the KMS key encrypting these secrets."
  value       = aws_kms_key.secrets.arn
}

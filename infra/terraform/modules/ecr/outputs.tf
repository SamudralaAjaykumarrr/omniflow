output "repository_urls" {
  description = "Map of service name -> full ECR repository URL, for use as an ECS task definition's container image (with a tag appended)."
  value       = { for name, repo in aws_ecr_repository.this : name => repo.repository_url }
}

output "repository_arns" {
  description = "Map of service name -> ECR repository ARN, for IAM policy scoping."
  value       = { for name, repo in aws_ecr_repository.this : name => repo.arn }
}

output "kms_key_arn" {
  description = "ARN of the KMS key encrypting these repositories."
  value       = aws_kms_key.ecr.arn
}

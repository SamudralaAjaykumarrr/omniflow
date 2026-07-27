output "alb_security_group_id" {
  description = "Security group attached to the ALB."
  value       = aws_security_group.alb.id
}

output "ecs_service_security_group_id" {
  description = "Shared security group attached to every ECS Fargate service/task."
  value       = aws_security_group.ecs_service.id
}

output "emr_serverless_security_group_id" {
  description = "Security group attached to EMR Serverless' VPC connectivity."
  value       = aws_security_group.emr_serverless.id
}

output "rds_security_group_id" {
  description = "Security group attached to the RDS instance."
  value       = aws_security_group.rds.id
}

output "msk_security_group_id" {
  description = "Security group attached to the MSK cluster's brokers."
  value       = aws_security_group.msk.id
}

output "elasticache_security_group_id" {
  description = "Security group attached to the ElastiCache Redis replication group."
  value       = aws_security_group.elasticache.id
}

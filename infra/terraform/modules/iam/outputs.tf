output "ecs_task_execution_role_arn" {
  description = "Shared ECS task-execution role ARN (ECR pull, log write, container-secrets resolution) — used by every service's task definition."
  value       = aws_iam_role.ecs_task_execution.arn
}

output "ecs_task_role_arns" {
  description = "Map of ECS logical service name -> its own task role ARN."
  value       = { for name, role in aws_iam_role.ecs_task : name => role.arn }
}

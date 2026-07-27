output "cluster_id" {
  description = "ECS cluster ID."
  value       = aws_ecs_cluster.this.id
}

output "cluster_name" {
  description = "ECS cluster name."
  value       = aws_ecs_cluster.this.name
}

output "service_discovery_namespace" {
  description = "Private DNS namespace name — a discoverable service's hostname is \"<service-name>.<this value>\", e.g. order-service.omniflow-dev.local."
  value       = aws_service_discovery_private_dns_namespace.this.name
}

output "task_definition_arns" {
  description = "Map of service name -> its latest ECS task definition ARN."
  value       = { for name, td in aws_ecs_task_definition.this : name => td.arn }
}

output "service_arns" {
  description = "Map of service name -> its ECS service ARN."
  value       = { for name, svc in aws_ecs_service.this : name => svc.id }
}

output "log_group_names" {
  description = "Map of service name -> its CloudWatch log group name."
  value       = { for name, lg in aws_cloudwatch_log_group.this : name => lg.name }
}

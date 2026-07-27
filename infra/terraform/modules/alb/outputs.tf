output "alb_arn" {
  description = "ALB ARN."
  value       = aws_lb.this.arn
}

output "alb_arn_suffix" {
  description = "ALB's arn_suffix — the exact dimension value CloudWatch's AWS/ApplicationELB metrics use (not the same string as the full ARN)."
  value       = aws_lb.this.arn_suffix
}

output "alb_dns_name" {
  description = "ALB's default DNS name — point a CNAME/ALIAS record at this from Route 53 or any other DNS provider (not created by this Terraform)."
  value       = aws_lb.this.dns_name
}

output "alb_zone_id" {
  description = "ALB's hosted zone ID, for a Route 53 ALIAS record."
  value       = aws_lb.this.zone_id
}

output "api_gateway_target_group_arn" {
  description = "Target group ARN api-gateway's ECS service registers into."
  value       = aws_lb_target_group.api_gateway.arn
}

output "ops_dashboard_target_group_arn" {
  description = "Target group ARN ops-dashboard's ECS service registers into."
  value       = aws_lb_target_group.ops_dashboard.arn
}

output "https_listener_arn" {
  description = "HTTPS listener ARN."
  value       = aws_lb_listener.https.arn
}

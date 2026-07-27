output "alarms_sns_topic_arn" {
  description = "SNS topic ARN every alarm publishes to."
  value       = aws_sns_topic.alarms.arn
}

output "dashboard_name" {
  description = "CloudWatch dashboard name."
  value       = aws_cloudwatch_dashboard.this.dashboard_name
}

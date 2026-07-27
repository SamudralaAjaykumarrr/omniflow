variable "project" {
  description = "Project name, used in resource naming."
  type        = string
}

variable "environment" {
  description = "Environment name (dev/prod)."
  type        = string
}

variable "alarm_email" {
  description = "Email address to subscribe to the alarms SNS topic. Null (default) creates the topic with no subscription — confirming a real subscription requires clicking a confirmation link AWS emails, which this Terraform cannot do and must not be assumed to have happened."
  type        = string
  default     = null
}

variable "alb_arn_suffix" {
  description = "ALB's arn_suffix (not its full ARN) — the exact dimension value CloudWatch's AWS/ApplicationELB metrics use."
  type        = string
}

variable "ecs_cluster_name" {
  description = "ECS cluster name."
  type        = string
}

variable "ecs_service_names" {
  description = "ECS service names to alarm on CPU/memory (matches modules/ecs's aws_ecs_service.this[*].name)."
  type        = list(string)
}

variable "rds_instance_id" {
  description = "RDS instance identifier."
  type        = string
}

variable "msk_cluster_name" {
  description = "MSK cluster name."
  type        = string
}

variable "cpu_alarm_threshold_percent" {
  description = "ECS service CPU utilization alarm threshold, percent."
  type        = number
  default     = 85
}

variable "memory_alarm_threshold_percent" {
  description = "ECS service memory utilization alarm threshold, percent."
  type        = number
  default     = 85
}

variable "alb_5xx_alarm_threshold" {
  description = "ALB target-origin 5xx count alarm threshold over a 5-minute period."
  type        = number
  default     = 10
}

variable "rds_cpu_alarm_threshold_percent" {
  description = "RDS CPU utilization alarm threshold, percent."
  type        = number
  default     = 80
}

variable "rds_free_storage_alarm_threshold_bytes" {
  description = "RDS free storage space alarm threshold, bytes (default 5 GB)."
  type        = number
  default     = 5368709120
}

variable "tags" {
  description = "Common tags applied to every resource this module creates."
  type        = map(string)
  default     = {}
}

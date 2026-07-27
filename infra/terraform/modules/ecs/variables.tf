variable "project" {
  description = "Project name, used in resource naming."
  type        = string
}

variable "environment" {
  description = "Environment name (dev/prod)."
  type        = string
}

variable "vpc_id" {
  description = "VPC ID."
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs ECS tasks run in (awsvpc network mode, no public IP)."
  type        = list(string)
}

variable "security_group_id" {
  description = "Shared ECS application security group (from modules/security)."
  type        = string
}

variable "task_execution_role_arn" {
  description = "Shared ECS task-execution role ARN (from modules/iam)."
  type        = string
}

variable "ecr_repository_urls" {
  description = "Map of image name (from modules/ecr's repository_names) -> full ECR repository URL."
  type        = map(string)
}

variable "container_insights_enabled" {
  description = "Enable CloudWatch Container Insights (per-task/service CPU, memory, network metrics beyond the default ECS metrics)."
  type        = bool
  default     = true
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention for every service's log group."
  type        = number
  default     = 30
}

# One entry per deployable ECS process — this maps 1:1 onto
# docker-compose.yml's own service list for the application tier (api-gateway,
# order-service + its validator-consumer + its outbox-relay, inventory-service
# + its outbox-relay, fulfillment-orchestrator + its consumer + its
# outbox-relay, failure-lab + its poison-consumer, ops-dashboard). Workers
# reuse the same image as their parent FastAPI service with a different
# `command`, exactly like docker-compose.yml's own command: overrides.
variable "services" {
  description = "Map of ECS logical service name -> its deployment spec."
  type = map(object({
    image_repo_key   = string
    image_tag        = optional(string, "latest")
    command          = optional(list(string))
    cpu              = number
    memory           = number
    container_port   = optional(number)
    desired_count    = number
    min_capacity     = optional(number)
    max_capacity     = optional(number)
    task_role_arn    = string
    environment      = optional(map(string), {})
    secrets          = optional(map(string), {})
    target_group_arn = optional(string)
    discoverable     = optional(bool, false)
  }))
}

variable "tags" {
  description = "Common tags applied to every resource this module creates."
  type        = map(string)
  default     = {}
}

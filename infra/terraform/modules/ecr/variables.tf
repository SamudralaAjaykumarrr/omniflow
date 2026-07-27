variable "project" {
  description = "Project name, used in repository naming."
  type        = string
}

variable "environment" {
  description = "Environment name (dev/prod)."
  type        = string
}

variable "repository_names" {
  description = "Logical service names to create one ECR repository per service for. Matches services/<name> in the monorepo — order-service, inventory-service, fulfillment-orchestrator, api-gateway, data-platform, ops-dashboard, failure-lab."
  type        = list(string)
  default = [
    "order-service",
    "inventory-service",
    "fulfillment-orchestrator",
    "api-gateway",
    "data-platform",
    "ops-dashboard",
    "failure-lab",
  ]
}

variable "image_tag_mutability" {
  description = "IMMUTABLE prevents a pushed tag (e.g. a git-sha tag) from ever being overwritten, so an ECS task definition pinned to a tag can never silently start pulling different bytes."
  type        = string
  default     = "IMMUTABLE"
}

variable "untagged_image_expiry_days" {
  description = "Days after which untagged images (superseded by a newer push of the same tag) are expired by the lifecycle policy, to bound storage cost."
  type        = number
  default     = 14
}

variable "max_tagged_images_per_repo" {
  description = "Maximum number of tagged images retained per repository before the oldest are expired by the lifecycle policy."
  type        = number
  default     = 30
}

variable "tags" {
  description = "Common tags applied to every repository."
  type        = map(string)
  default     = {}
}

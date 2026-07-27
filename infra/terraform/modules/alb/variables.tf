variable "project" {
  description = "Project name, used in resource naming."
  type        = string
}

variable "environment" {
  description = "Environment name (dev/prod)."
  type        = string
}

variable "vpc_id" {
  description = "VPC ID the ALB and its target groups belong to."
  type        = string
}

variable "public_subnet_ids" {
  description = "Public subnet IDs the internet-facing ALB is placed in."
  type        = list(string)
}

variable "security_group_id" {
  description = "Security group for the ALB (from modules/security)."
  type        = string
}

variable "certificate_arn" {
  description = "ACM certificate ARN for the HTTPS listener. Must be issued/validated out-of-band (ACM certificate issuance needs a real, owned domain — out of this Terraform's scope). A placeholder value in terraform.tfvars.example only; terraform validate does not check that it resolves to a real certificate."
  type        = string
}

variable "dashboard_hostname" {
  description = "Host header routed to the ops-dashboard target group; every other Host goes to api-gateway (the customer-facing entry point, matching docs/architecture.md's ALB -> API Gateway flow). Must resolve to the ALB via Route 53 or equivalent DNS out-of-band — no Route 53 zone is created by this Terraform."
  type        = string
  default     = "ops.omniflow.example"
}

variable "app_port" {
  description = "Container port api-gateway listens on internally (matches modules/security's app_port and the service's own Dockerfile EXPOSE)."
  type        = number
  default     = 8000
}

variable "dashboard_port" {
  description = "Container port ops-dashboard's nginx listens on internally (matches modules/security's dashboard_port)."
  type        = number
  default     = 80
}

variable "api_gateway_health_check_path" {
  description = "api-gateway's real health endpoint (services/api-gateway exposes GET /healthz)."
  type        = string
  default     = "/healthz"
}

variable "ops_dashboard_health_check_path" {
  description = "ops-dashboard's health endpoint — its nginx serves the SPA's index at /."
  type        = string
  default     = "/"
}

variable "idle_timeout_seconds" {
  description = "ALB idle connection timeout."
  type        = number
  default     = 60
}

variable "deletion_protection" {
  description = "Prevents accidental ALB deletion via console/API without first disabling this flag."
  type        = bool
  default     = false
}

variable "tags" {
  description = "Common tags applied to every resource this module creates."
  type        = map(string)
  default     = {}
}

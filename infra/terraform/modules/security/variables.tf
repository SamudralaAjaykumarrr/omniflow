variable "project" {
  description = "Project name, used in resource naming."
  type        = string
}

variable "environment" {
  description = "Environment name (dev/prod)."
  type        = string
}

variable "vpc_id" {
  description = "VPC ID these security groups belong to."
  type        = string
}

variable "vpc_cidr" {
  description = "VPC CIDR block, used for VPC-internal-only ingress rules."
  type        = string
}

variable "alb_ingress_cidrs" {
  description = "CIDR blocks allowed to reach the ALB on 443/80. Restrict this in prod (e.g. a corporate/VPN range); 0.0.0.0/0 is a portfolio-demo default, not a production posture."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "app_port" {
  description = "Container port every FastAPI service (api-gateway, order-service, inventory-service, fulfillment-orchestrator, failure-lab) listens on internally — matches EXPOSE 8000 in every service's Dockerfile."
  type        = number
  default     = 8000
}

variable "dashboard_port" {
  description = "Container port the ops-dashboard's nginx listens on — matches its Dockerfile's EXPOSE 80."
  type        = number
  default     = 80
}

variable "tags" {
  description = "Common tags applied to every resource this module creates."
  type        = map(string)
  default     = {}
}

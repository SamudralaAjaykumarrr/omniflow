variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Project name, used throughout resource naming/tags."
  type        = string
  default     = "omniflow"
}

variable "environment" {
  description = "Environment name."
  type        = string
  default     = "prod"
}

# --- Networking --------------------------------------------------------
variable "vpc_cidr" {
  type    = string
  default = "10.1.0.0/16"
}

variable "azs" {
  type    = list(string)
  default = ["us-east-1a", "us-east-1b", "us-east-1c"]
}

variable "public_subnet_cidrs" {
  type    = list(string)
  default = ["10.1.0.0/24", "10.1.1.0/24", "10.1.2.0/24"]
}

variable "private_subnet_cidrs" {
  type    = list(string)
  default = ["10.1.10.0/24", "10.1.11.0/24", "10.1.12.0/24"]
}

variable "single_nat_gateway" {
  description = "Prod default: one NAT gateway per AZ (availability over the dev environment's cost-optimized single shared NAT)."
  type        = bool
  default     = false
}

variable "alb_ingress_cidrs" {
  description = "CIDRs allowed to reach the ALB. Restrict this to real known ranges before any production use — 0.0.0.0/0 here is a portfolio-demo placeholder, not a production posture."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

# --- DNS / TLS -----------------------------------------------------------
variable "certificate_arn" {
  description = "ACM certificate ARN for the ALB's HTTPS listener. Must already exist (issued/validated out-of-band against a real, owned domain) — see README. A placeholder value only; never resolved by terraform validate."
  type        = string
}

variable "dashboard_hostname" {
  description = "Host header routed to ops-dashboard; every other Host goes to api-gateway."
  type        = string
  default     = "ops.omniflow.example"
}

# --- S3 --------------------------------------------------------------------
variable "data_lake_bucket_suffix" {
  description = "Suffix appended to the data-lake bucket name for global uniqueness (e.g. your AWS account ID). Set this in terraform.tfvars — never commit a real value."
  type        = string
}

# --- RDS ---------------------------------------------------------------
variable "rds_instance_class" {
  type    = string
  default = "db.r6g.large"
}

variable "rds_multi_az" {
  description = "Prod default: standby replica for automatic failover."
  type        = bool
  default     = true
}

variable "rds_allocated_storage_gb" {
  type    = number
  default = 200
}

variable "rds_deletion_protection" {
  description = "Prod default: on. Must be explicitly disabled before any `terraform destroy` of this resource — deliberate friction."
  type        = bool
  default     = true
}

# --- MSK -----------------------------------------------------------------
variable "msk_broker_instance_type" {
  type    = string
  default = "kafka.m5.large"
}

variable "msk_broker_count" {
  description = "Must be a whole multiple of length(var.azs). Null defaults to exactly one broker per AZ (3, matching var.azs above)."
  type        = number
  default     = null
}

# --- ElastiCache -----------------------------------------------------------
variable "elasticache_node_type" {
  type    = string
  default = "cache.r6g.large"
}

variable "elasticache_num_cache_clusters" {
  description = "Prod default: 2 (1 primary + 1 replica, automatic failover)."
  type        = number
  default     = 2
}

variable "elasticache_automatic_failover_enabled" {
  description = "Requires elasticache_num_cache_clusters >= 2. Prod default: on."
  type        = bool
  default     = true
}

# --- EMR Serverless ----------------------------------------------------
variable "emr_max_capacity_cpu" {
  type    = string
  default = "64 vCPU"
}

variable "emr_max_capacity_memory_gb" {
  type    = string
  default = "256 GB"
}

# --- ECS / images ------------------------------------------------------
variable "image_tag" {
  description = "Image tag every ECS task definition pulls. Prod should always pin a specific CI-built git-sha tag, never 'latest' — the default here is a placeholder, not a recommendation."
  type        = string
  default     = "latest"
}

variable "gateway_rate_limit_per_minute" {
  description = "Matches api-gateway's GATEWAY_RATE_LIMIT_PER_MINUTE — same default as .env.example."
  type        = number
  default     = 120
}

# --- Observability -------------------------------------------------------
variable "alarm_email" {
  description = "Optional email to subscribe to the CloudWatch alarms SNS topic. Leave null to skip (see modules/observability's note on why a subscription can't be confirmed by Terraform)."
  type        = string
  default     = null
}

locals {
  common_tags = {
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "terraform"
    Repository  = "omniflow"
  }
}

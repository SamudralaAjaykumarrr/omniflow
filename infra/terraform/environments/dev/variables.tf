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
  default     = "dev"
}

# --- Networking --------------------------------------------------------
variable "vpc_cidr" {
  type    = string
  default = "10.0.0.0/16"
}

variable "azs" {
  type    = list(string)
  default = ["us-east-1a", "us-east-1b"]
}

variable "public_subnet_cidrs" {
  type    = list(string)
  default = ["10.0.0.0/24", "10.0.1.0/24"]
}

variable "private_subnet_cidrs" {
  type    = list(string)
  default = ["10.0.10.0/24", "10.0.11.0/24"]
}

variable "single_nat_gateway" {
  description = "Dev default: one shared NAT gateway (cost over availability)."
  type        = bool
  default     = true
}

variable "alb_ingress_cidrs" {
  description = "CIDRs allowed to reach the ALB. Restrict this for anything beyond a portfolio demo."
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
  default     = "ops-dev.omniflow.example"
}

# --- S3 --------------------------------------------------------------------
variable "data_lake_bucket_suffix" {
  description = "Suffix appended to the data-lake bucket name for global uniqueness (e.g. your AWS account ID). Set this in terraform.tfvars — never commit a real value."
  type        = string
}

# --- RDS ---------------------------------------------------------------
variable "rds_instance_class" {
  type    = string
  default = "db.t4g.medium"
}

variable "rds_multi_az" {
  type    = bool
  default = false
}

variable "rds_allocated_storage_gb" {
  type    = number
  default = 50
}

variable "rds_deletion_protection" {
  type    = bool
  default = false
}

# --- MSK -----------------------------------------------------------------
variable "msk_broker_instance_type" {
  type    = string
  default = "kafka.t3.small"
}

variable "msk_broker_count" {
  description = "Must be a whole multiple of length(var.azs). Null defaults to exactly one broker per AZ."
  type        = number
  default     = null
}

# --- ElastiCache -----------------------------------------------------------
variable "elasticache_node_type" {
  type    = string
  default = "cache.t4g.micro"
}

variable "elasticache_num_cache_clusters" {
  type    = number
  default = 1
}

variable "elasticache_automatic_failover_enabled" {
  description = "Requires elasticache_num_cache_clusters >= 2. Dev default: off (single node, no replica)."
  type        = bool
  default     = false
}

# --- EMR Serverless ----------------------------------------------------
variable "emr_max_capacity_cpu" {
  type    = string
  default = "16 vCPU"
}

variable "emr_max_capacity_memory_gb" {
  type    = string
  default = "64 GB"
}

# --- ECS / images ------------------------------------------------------
variable "image_tag" {
  description = "Image tag every ECS task definition pulls — a real deploy would set this to a CI-built git-sha tag, never 'latest' in prod."
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

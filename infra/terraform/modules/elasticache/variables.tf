variable "project" {
  description = "Project name, used in resource naming."
  type        = string
}

variable "environment" {
  description = "Environment name (dev/prod)."
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs for the cache subnet group."
  type        = list(string)
}

variable "security_group_id" {
  description = "Security group allowing ECS services in on 6379 (from modules/security)."
  type        = string
}

variable "node_type" {
  description = "ElastiCache node type. cache.t4g.micro is a reasonable dev default (burstable, Graviton)."
  type        = string
  default     = "cache.t4g.micro"
}

variable "num_cache_clusters" {
  description = "Number of nodes in the replication group (1 primary + N-1 replicas). 1 = no replica (dev default); use >= 2 in prod for automatic failover."
  type        = number
  default     = 1
}

variable "engine_version" {
  description = "Redis engine version."
  type        = string
  default     = "7.1"
}

variable "automatic_failover_enabled" {
  description = "Requires num_cache_clusters >= 2. Enables automatic failover to a replica if the primary node fails."
  type        = bool
  default     = false
}

variable "snapshot_retention_days" {
  description = "Days to retain automatic daily snapshots. 0 disables snapshots (dev default, no persistence guarantee needed for a rate-limiter cache)."
  type        = number
  default     = 0
}

variable "tags" {
  description = "Common tags applied to every resource this module creates."
  type        = map(string)
  default     = {}
}

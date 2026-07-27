variable "project" {
  description = "Project name, used in resource naming."
  type        = string
}

variable "environment" {
  description = "Environment name (dev/prod)."
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs brokers are placed in — one broker per subnet per broker_count multiple."
  type        = list(string)
}

variable "security_group_id" {
  description = "Security group allowing ECS services / EMR Serverless in on the IAM-auth and TLS broker ports (from modules/security)."
  type        = string
}

variable "broker_instance_type" {
  description = "MSK broker instance type. kafka.t3.small is a reasonable dev default (burstable); size up for prod."
  type        = string
  default     = "kafka.t3.small"
}

variable "broker_count" {
  description = "Total broker count — must be a whole multiple of length(private_subnet_ids) (one broker per subnet per multiple). Defaults to exactly one broker per subnet."
  type        = number
  default     = null
}

variable "broker_ebs_volume_size_gb" {
  description = "Per-broker EBS volume size, GB."
  type        = number
  default     = 100
}

variable "kafka_version" {
  description = "MSK Kafka version. Redpanda locally advertises Kafka-protocol compatibility with this line (docker-compose.yml pins redpanda v24.2.18)."
  type        = string
  default     = "3.6.0"
}

variable "num_partitions_default" {
  description = "Default partition count for auto-created topics. Topics are explicitly created (matching local's infra/docker/redpanda/create-topics.sh, auto.create.topics.enable=false below), so this mostly documents intent for any topic created out-of-band."
  type        = number
  default     = 6
}

variable "default_replication_factor" {
  description = "Default replication factor for new topics — 3 needs at least 3 brokers/AZs; keep in sync with broker_count."
  type        = number
  default     = 3
}

variable "log_retention_hours" {
  description = "Broker-level default log retention, hours (168 = 7 days)."
  type        = number
  default     = 168
}

variable "cloudwatch_log_retention_days" {
  description = "Retention for MSK's broker logs delivered to CloudWatch Logs."
  type        = number
  default     = 14
}

variable "tags" {
  description = "Common tags applied to every resource this module creates."
  type        = map(string)
  default     = {}
}

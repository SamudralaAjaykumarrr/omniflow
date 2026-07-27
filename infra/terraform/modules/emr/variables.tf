variable "project" {
  description = "Project name, used in resource naming."
  type        = string
}

variable "environment" {
  description = "Environment name (dev/prod)."
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs for EMR Serverless' VPC connectivity (to reach MSK privately)."
  type        = list(string)
}

variable "security_group_id" {
  description = "Security group for EMR Serverless' ENIs (from modules/security, egress-only)."
  type        = string
}

variable "release_label" {
  description = "EMR release line. Pinned to an EMR 7.x line shipping Spark 3.5.x, matching services/data-platform's pyspark==3.5.3 pin so job code behaves identically to local `local[*]` mode (ADR 0005)."
  type        = string
  default     = "emr-7.1.0"
}

variable "s3_bucket_arn" {
  description = "Data-lake bucket ARN (from modules/s3) — Bronze/Silver/Gold read/write."
  type        = string
}

variable "s3_kms_key_arn" {
  description = "KMS key ARN encrypting the data-lake bucket — execution role needs kms:Decrypt/GenerateDataKey to read/write it."
  type        = string
}

variable "msk_cluster_arn" {
  description = "MSK cluster ARN — Spark's Kafka source connector needs IAM-auth client permissions to consume the event catalog, same as the ECS Kafka-touching services."
  type        = string
}

variable "pre_init_capacity_cpu" {
  description = "Pre-initialized driver/executor capacity (vCPU) kept warm to cut cold-start latency for scheduled batch runs — 0 disables pre-initialization (cheapest, cold start on every run)."
  type        = number
  default     = 0
}

variable "max_capacity_cpu" {
  description = "Maximum total vCPU EMR Serverless will scale a single application up to across all concurrent job runs."
  type        = string
  default     = "16 vCPU"
}

variable "max_capacity_memory_gb" {
  description = "Maximum total memory EMR Serverless will scale a single application up to across all concurrent job runs."
  type        = string
  default     = "64 GB"
}

variable "idle_timeout_minutes" {
  description = "Minutes of no running job before EMR Serverless auto-stops the application (billing stops entirely between runs — a key cost advantage over an always-on EMR-on-EC2 cluster for this workload's bursty batch/streaming-restart pattern)."
  type        = number
  default     = 15
}

variable "tags" {
  description = "Common tags applied to every resource this module creates."
  type        = map(string)
  default     = {}
}

variable "project" {
  description = "Project name, used in role naming."
  type        = string
}

variable "environment" {
  description = "Environment name (dev/prod)."
  type        = string
}

variable "secret_arns_for_execution_role" {
  description = "Secrets Manager ARNs the ECS task-execution role may read to inject as container-definition 'secrets' (env vars resolved at container start — the running application code itself never calls Secrets Manager for these). Typically: JWT secret, seeded demo-user passwords, RDS master-user secret, Redis auth token."
  type        = list(string)
}

variable "kms_key_arns_for_execution_role" {
  description = "KMS key ARNs used to encrypt the secrets above — the execution role needs kms:Decrypt on each to read them."
  type        = list(string)
}

variable "ecs_service_names_needing_kafka" {
  description = "ECS logical service names whose task role needs MSK IAM-auth client permissions (kafka-cluster:Connect + topic/group read-write) — the services/workers with their own Kafka producer/consumer: order-service (+ its validator-consumer/outbox-relay, same role), inventory-service (+ outbox-relay), fulfillment-orchestrator (+ consumer/outbox-relay), failure-lab (+ poison-consumer), and data-platform's lag-poller (polls consumer-group lag directly). api-gateway and ops-dashboard never touch Kafka directly, so they are excluded."
  type        = list(string)
  default = [
    "order-service",
    "inventory-service",
    "fulfillment-orchestrator",
    "failure-lab",
    "data-platform",
  ]
}

variable "ecs_service_names_needing_s3" {
  description = "ECS logical service names whose task role needs data-lake bucket access — only data-platform's lag-poller (writes the consumer_lag Gold dataset directly, independent of the Spark/EMR jobs)."
  type        = list(string)
  default     = ["data-platform"]
}

variable "ecs_service_names" {
  description = "All ECS logical service names needing their own (possibly empty-permission) task role. One role per group is shared by every ECS deployable in that group (e.g. order-service's API process, validator-consumer, and outbox-relay all use the \"order-service\" task role)."
  type        = list(string)
  default = [
    "api-gateway",
    "order-service",
    "inventory-service",
    "fulfillment-orchestrator",
    "failure-lab",
    "ops-dashboard",
    "data-platform",
  ]
}

variable "msk_cluster_arn" {
  description = "ARN of the MSK cluster, for scoping kafka-cluster:* IAM actions to exactly this cluster's topics/groups."
  type        = string
}

variable "s3_bucket_arn" {
  description = "Data-lake bucket ARN, for scoping the S3 policy attached to ecs_service_names_needing_s3."
  type        = string
}

variable "s3_kms_key_arn" {
  description = "KMS key ARN encrypting the data-lake bucket — needed alongside s3_bucket_arn for kms:Decrypt/GenerateDataKey."
  type        = string
}

variable "tags" {
  description = "Common tags applied to every role this module creates."
  type        = map(string)
  default     = {}
}

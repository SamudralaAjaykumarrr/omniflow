variable "project" {
  description = "Project name, used in bucket naming."
  type        = string
}

variable "environment" {
  description = "Environment name (dev/prod)."
  type        = string
}

variable "bucket_suffix" {
  description = "Extra suffix appended to the bucket name to keep it globally unique (S3 bucket names are global). Set to something account-specific, e.g. an AWS account ID or a random hex string — never hardcode a real value in version control."
  type        = string
}

variable "force_destroy" {
  description = "If true, allows Terraform to delete this bucket even if it still contains objects. Left false by default — this is a data lake, not disposable scratch space; a real destroy should empty it deliberately first."
  type        = bool
  default     = false
}

variable "noncurrent_version_expiration_days" {
  description = "Days after which a noncurrent (overwritten/deleted) object version is permanently expired, bounding versioning's storage cost."
  type        = number
  default     = 90
}

variable "standard_ia_transition_days" {
  description = "Days after which Bronze/Silver objects transition to STANDARD_IA (cheaper, still millisecond-latency) — Gold/forecasting output, read far more often, is left on STANDARD."
  type        = number
  default     = 30
}

variable "glacier_transition_days" {
  description = "Days after which Bronze objects (raw, replayable-from-Kafka-retention-window only in theory) transition to Glacier Instant Retrieval for long-term cheap storage."
  type        = number
  default     = 180
}

variable "tags" {
  description = "Common tags applied to the bucket."
  type        = map(string)
  default     = {}
}

variable "project" {
  description = "Project name, used in secret naming."
  type        = string
}

variable "environment" {
  description = "Environment name (dev/prod)."
  type        = string
}

variable "recovery_window_in_days" {
  description = "Secrets Manager recovery window before a deleted secret is permanently purged. 0 disables the recovery window entirely (immediate delete) — useful for a throwaway dev environment, never recommended for prod."
  type        = number
  default     = 7
}

variable "tags" {
  description = "Common tags applied to every secret."
  type        = map(string)
  default     = {}
}

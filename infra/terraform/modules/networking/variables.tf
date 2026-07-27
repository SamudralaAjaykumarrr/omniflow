variable "project" {
  description = "Project name, used in resource naming (e.g. \"omniflow\")."
  type        = string
}

variable "environment" {
  description = "Environment name (e.g. \"dev\", \"prod\") used in resource naming and tags."
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.0.0.0/16"
}

variable "azs" {
  description = "Availability zones to spread public/private subnets across. Exactly 2 for this design (MSK/RDS/ALB multi-AZ needs at least 2)."
  type        = list(string)

  validation {
    condition     = length(var.azs) >= 2
    error_message = "At least 2 availability zones are required for a multi-AZ-capable network."
  }
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for public subnets, one per AZ, same order as var.azs."
  type        = list(string)
}

variable "private_subnet_cidrs" {
  description = "CIDR blocks for private subnets, one per AZ, same order as var.azs."
  type        = list(string)
}

variable "single_nat_gateway" {
  description = "If true, provision one NAT gateway shared by every private subnet (cheaper, single point of failure for outbound internet). If false, one NAT gateway per AZ (highly available, ~2x NAT cost). See infra/terraform/README.md 'Cost considerations'."
  type        = bool
  default     = true
}

variable "tags" {
  description = "Common tags applied to every resource this module creates."
  type        = map(string)
  default     = {}
}

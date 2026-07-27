# Local state only, deliberately — see ADR 0007 (docs/adrs/0007-terraform-not-applied.md)
# and infra/terraform/README.md. This Terraform has never been applied, so
# no real state file with real resource IDs exists anywhere; a remote
# backend (S3 + DynamoDB lock table) is documented as the recommended
# production setup in the README, but deliberately NOT configured here —
# creating that bucket/table would itself be a real, billed AWS resource,
# which is exactly the boundary this project's standing rules forbid
# crossing autonomously.
#
# If this were ever actually deployed, uncomment and fill in a real,
# pre-existing bucket/table (never created by this same Terraform run,
# to avoid the classic chicken-and-egg bootstrap problem):
#
# terraform {
#   backend "s3" {
#     bucket         = "REPLACE_ME-omniflow-tfstate"
#     key            = "dev/terraform.tfstate"
#     region         = "us-east-1"
#     dynamodb_table = "REPLACE_ME-omniflow-tfstate-lock"
#     encrypt        = true
#   }
# }

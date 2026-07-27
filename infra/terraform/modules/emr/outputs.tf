output "application_id" {
  description = "EMR Serverless application ID — pass this to `aws emr-serverless start-job-run` to actually run a job (never done by this Terraform)."
  value       = aws_emrserverless_application.spark.id
}

output "application_arn" {
  description = "EMR Serverless application ARN."
  value       = aws_emrserverless_application.spark.arn
}

output "execution_role_arn" {
  description = "IAM role ARN a job run must pass as --execution-role-arn."
  value       = aws_iam_role.emr_execution.arn
}

output "bucket_id" {
  description = "Name of the data-lake bucket."
  value       = aws_s3_bucket.data_lake.id
}

output "bucket_arn" {
  description = "ARN of the data-lake bucket, for IAM policy scoping."
  value       = aws_s3_bucket.data_lake.arn
}

output "kms_key_arn" {
  description = "ARN of the KMS key encrypting this bucket."
  value       = aws_kms_key.data_lake.arn
}

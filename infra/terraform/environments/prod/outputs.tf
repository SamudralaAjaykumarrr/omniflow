output "alb_dns_name" {
  description = "Point a DNS CNAME/ALIAS record here (api-gateway is the default Host; var.dashboard_hostname routes to ops-dashboard)."
  value       = module.alb.alb_dns_name
}

output "ecr_repository_urls" {
  description = "Map of service name -> ECR repository URL, for `docker push`."
  value       = module.ecr.repository_urls
}

output "rds_endpoint" {
  description = "RDS connection endpoint (host:port). No password included."
  value       = module.rds.endpoint
}

output "rds_master_password_secret_arn" {
  description = "Secrets Manager ARN holding the RDS master password — needed for the documented post-provision per-service-database bootstrap step (see README)."
  value       = module.secrets.rds_master_password_secret_arn
}

output "msk_bootstrap_brokers_sasl_iam" {
  description = "MSK bootstrap broker connection string (IAM auth)."
  value       = module.msk.bootstrap_brokers_sasl_iam
}

output "data_lake_bucket_id" {
  description = "S3 data-lake bucket name."
  value       = module.s3.bucket_id
}

output "emr_serverless_application_id" {
  description = "EMR Serverless application ID — pass to `aws emr-serverless start-job-run` to actually run a Bronze/Silver/Gold job (never done by this Terraform)."
  value       = module.emr.application_id
}

output "ecs_cluster_name" {
  description = "ECS cluster name."
  value       = module.ecs.cluster_name
}

output "cloudwatch_dashboard_name" {
  description = "CloudWatch dashboard name — view it in the console under CloudWatch > Dashboards."
  value       = module.observability.dashboard_name
}

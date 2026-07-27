module "networking" {
  source = "../../modules/networking"

  project              = var.project
  environment          = var.environment
  vpc_cidr             = var.vpc_cidr
  azs                  = var.azs
  public_subnet_cidrs  = var.public_subnet_cidrs
  private_subnet_cidrs = var.private_subnet_cidrs
  single_nat_gateway   = var.single_nat_gateway
  tags                 = local.common_tags
}

module "security" {
  source = "../../modules/security"

  project           = var.project
  environment       = var.environment
  vpc_id            = module.networking.vpc_id
  vpc_cidr          = module.networking.vpc_cidr
  alb_ingress_cidrs = var.alb_ingress_cidrs
  tags              = local.common_tags
}

module "ecr" {
  source = "../../modules/ecr"

  project     = var.project
  environment = var.environment
  tags        = local.common_tags
}

module "secrets" {
  source = "../../modules/secrets"

  project     = var.project
  environment = var.environment
  tags        = local.common_tags
}

module "s3" {
  source = "../../modules/s3"

  project       = var.project
  environment   = var.environment
  bucket_suffix = var.data_lake_bucket_suffix
  tags          = local.common_tags
}

module "rds" {
  source = "../../modules/rds"

  project              = var.project
  environment          = var.environment
  private_subnet_ids   = module.networking.private_subnet_ids
  security_group_id    = module.security.rds_security_group_id
  instance_class       = var.rds_instance_class
  multi_az             = var.rds_multi_az
  allocated_storage_gb = var.rds_allocated_storage_gb
  deletion_protection  = var.rds_deletion_protection
  master_password      = module.secrets.rds_master_password
  tags                 = local.common_tags
}

module "elasticache" {
  source = "../../modules/elasticache"

  project                    = var.project
  environment                = var.environment
  private_subnet_ids         = module.networking.private_subnet_ids
  security_group_id          = module.security.elasticache_security_group_id
  node_type                  = var.elasticache_node_type
  num_cache_clusters         = var.elasticache_num_cache_clusters
  automatic_failover_enabled = var.elasticache_automatic_failover_enabled
  tags                       = local.common_tags
}

module "msk" {
  source = "../../modules/msk"

  project              = var.project
  environment          = var.environment
  private_subnet_ids   = module.networking.private_subnet_ids
  security_group_id    = module.security.msk_security_group_id
  broker_instance_type = var.msk_broker_instance_type
  broker_count         = var.msk_broker_count
  tags                 = local.common_tags
}

module "iam" {
  source = "../../modules/iam"

  project         = var.project
  environment     = var.environment
  msk_cluster_arn = module.msk.cluster_arn

  secret_arns_for_execution_role = concat(
    [
      module.secrets.jwt_secret_key_secret_arn,
    ],
    values(module.secrets.seed_password_secret_arns),
    values(local.database_url_secret_arns),
  )

  kms_key_arns_for_execution_role = [
    module.secrets.kms_key_arn,
    module.rds.kms_key_arn,
  ]

  s3_bucket_arn  = module.s3.bucket_arn
  s3_kms_key_arn = module.s3.kms_key_arn

  tags = local.common_tags
}

module "emr" {
  source = "../../modules/emr"

  project                = var.project
  environment            = var.environment
  private_subnet_ids     = module.networking.private_subnet_ids
  security_group_id      = module.security.emr_serverless_security_group_id
  s3_bucket_arn          = module.s3.bucket_arn
  s3_kms_key_arn         = module.s3.kms_key_arn
  msk_cluster_arn        = module.msk.cluster_arn
  max_capacity_cpu       = var.emr_max_capacity_cpu
  max_capacity_memory_gb = var.emr_max_capacity_memory_gb
  tags                   = local.common_tags
}

module "alb" {
  source = "../../modules/alb"

  project            = var.project
  environment        = var.environment
  vpc_id             = module.networking.vpc_id
  public_subnet_ids  = module.networking.public_subnet_ids
  security_group_id  = module.security.alb_security_group_id
  certificate_arn    = var.certificate_arn
  dashboard_hostname = var.dashboard_hostname
  tags               = local.common_tags
}

module "ecs" {
  source = "../../modules/ecs"

  project                 = var.project
  environment             = var.environment
  vpc_id                  = module.networking.vpc_id
  private_subnet_ids      = module.networking.private_subnet_ids
  security_group_id       = module.security.ecs_service_security_group_id
  task_execution_role_arn = module.iam.ecs_task_execution_role_arn
  ecr_repository_urls     = module.ecr.repository_urls
  services                = local.ecs_services
  tags                    = local.common_tags
}

module "observability" {
  source = "../../modules/observability"

  project           = var.project
  environment       = var.environment
  alarm_email       = var.alarm_email
  alb_arn_suffix    = module.alb.alb_arn_suffix
  ecs_cluster_name  = module.ecs.cluster_name
  ecs_service_names = keys(local.ecs_services)
  rds_instance_id   = module.rds.identifier
  msk_cluster_name  = module.msk.cluster_name
  tags              = local.common_tags
}

# Every ECS Fargate deployable, mirroring docker-compose.yml's own service
# list for the application tier. Workers reuse their parent FastAPI
# service's image with a different `command`, exactly like
# docker-compose.yml's own command: overrides — and, correspondingly, share
# that same logical group's IAM task role (module.iam.ecs_task_role_arns).
#
# Hostnames use the ECS module's deterministic Cloud Map namespace name
# ("<project>-<environment>.local") directly, rather than a module output,
# since it's fully determined by input variables and referencing it this
# way avoids a dependency cycle (module.ecs's own `services` input needs
# these hostnames to build each service's environment map).

locals {
  dns_suffix = "${var.project}-${var.environment}.local"

  order_service_internal_url     = "http://order-service.${local.dns_suffix}:8000"
  inventory_service_internal_url = "http://inventory-service.${local.dns_suffix}:8000"
  orchestrator_internal_url      = "http://fulfillment-orchestrator.${local.dns_suffix}:8000"
  gateway_internal_url           = "http://api-gateway.${local.dns_suffix}:8000"

  msk_bootstrap = module.msk.bootstrap_brokers_sasl_iam

  ecs_services = {
    "order-service" = {
      image_repo_key = "order-service"
      image_tag      = var.image_tag
      cpu            = 512
      memory         = 1024
      container_port = 8000
      desired_count  = 1
      min_capacity   = 1
      max_capacity   = 3
      task_role_arn  = module.iam.ecs_task_role_arns["order-service"]
      discoverable   = true
      secrets = {
        ORDER_SERVICE_DATABASE_URL = local.database_url_secret_arns["order-service"]
      }
    }

    "order-validator-consumer" = {
      image_repo_key = "order-service"
      image_tag      = var.image_tag
      command        = ["python", "-m", "app.validator_consumer"]
      cpu            = 256
      memory         = 512
      desired_count  = 1
      min_capacity   = 1
      max_capacity   = 2
      task_role_arn  = module.iam.ecs_task_role_arns["order-service"]
      discoverable   = false
      environment = {
        KAFKA_BOOTSTRAP_SERVERS = local.msk_bootstrap
        METRICS_PORT            = "9102"
      }
      secrets = {
        ORDER_SERVICE_DATABASE_URL = local.database_url_secret_arns["order-service"]
      }
    }

    "order-outbox-relay" = {
      image_repo_key = "order-service"
      image_tag      = var.image_tag
      command        = ["python", "-m", "app.outbox_relay"]
      cpu            = 256
      memory         = 512
      desired_count  = 1
      min_capacity   = 1
      max_capacity   = 2
      task_role_arn  = module.iam.ecs_task_role_arns["order-service"]
      discoverable   = false
      environment = {
        KAFKA_BOOTSTRAP_SERVERS = local.msk_bootstrap
        METRICS_PORT            = "9101"
      }
      secrets = {
        ORDER_SERVICE_DATABASE_URL = local.database_url_secret_arns["order-service"]
      }
    }

    "inventory-service" = {
      image_repo_key = "inventory-service"
      image_tag      = var.image_tag
      cpu            = 512
      memory         = 1024
      container_port = 8000
      desired_count  = 1
      min_capacity   = 1
      max_capacity   = 3
      task_role_arn  = module.iam.ecs_task_role_arns["inventory-service"]
      discoverable   = true
      secrets = {
        INVENTORY_SERVICE_DATABASE_URL = local.database_url_secret_arns["inventory-service"]
      }
    }

    "inventory-outbox-relay" = {
      image_repo_key = "inventory-service"
      image_tag      = var.image_tag
      command        = ["python", "-m", "app.outbox_relay"]
      cpu            = 256
      memory         = 512
      desired_count  = 1
      min_capacity   = 1
      max_capacity   = 2
      task_role_arn  = module.iam.ecs_task_role_arns["inventory-service"]
      discoverable   = false
      environment = {
        KAFKA_BOOTSTRAP_SERVERS = local.msk_bootstrap
        METRICS_PORT            = "9103"
      }
      secrets = {
        INVENTORY_SERVICE_DATABASE_URL = local.database_url_secret_arns["inventory-service"]
      }
    }

    "fulfillment-orchestrator" = {
      image_repo_key = "fulfillment-orchestrator"
      image_tag      = var.image_tag
      cpu            = 512
      memory         = 1024
      container_port = 8000
      desired_count  = 1
      min_capacity   = 1
      max_capacity   = 3
      task_role_arn  = module.iam.ecs_task_role_arns["fulfillment-orchestrator"]
      discoverable   = true
      environment = {
        ORCHESTRATOR_ORDER_SERVICE_URL     = local.order_service_internal_url
        ORCHESTRATOR_INVENTORY_SERVICE_URL = local.inventory_service_internal_url
      }
      secrets = {
        ORCHESTRATOR_DATABASE_URL = local.database_url_secret_arns["fulfillment-orchestrator"]
      }
    }

    "fulfillment-orchestrator-consumer" = {
      image_repo_key = "fulfillment-orchestrator"
      image_tag      = var.image_tag
      command        = ["python", "-m", "app.consumer"]
      cpu            = 256
      memory         = 512
      desired_count  = 1
      min_capacity   = 1
      max_capacity   = 2
      task_role_arn  = module.iam.ecs_task_role_arns["fulfillment-orchestrator"]
      discoverable   = false
      environment = {
        ORCHESTRATOR_ORDER_SERVICE_URL     = local.order_service_internal_url
        ORCHESTRATOR_INVENTORY_SERVICE_URL = local.inventory_service_internal_url
        KAFKA_BOOTSTRAP_SERVERS            = local.msk_bootstrap
        METRICS_PORT                       = "9104"
      }
      secrets = {
        ORCHESTRATOR_DATABASE_URL = local.database_url_secret_arns["fulfillment-orchestrator"]
      }
    }

    "fulfillment-orchestrator-outbox-relay" = {
      image_repo_key = "fulfillment-orchestrator"
      image_tag      = var.image_tag
      command        = ["python", "-m", "app.outbox_relay"]
      cpu            = 256
      memory         = 512
      desired_count  = 1
      min_capacity   = 1
      max_capacity   = 2
      task_role_arn  = module.iam.ecs_task_role_arns["fulfillment-orchestrator"]
      discoverable   = false
      environment = {
        KAFKA_BOOTSTRAP_SERVERS = local.msk_bootstrap
        METRICS_PORT            = "9105"
      }
      secrets = {
        ORCHESTRATOR_DATABASE_URL = local.database_url_secret_arns["fulfillment-orchestrator"]
      }
    }

    "api-gateway" = {
      image_repo_key   = "api-gateway"
      image_tag        = var.image_tag
      cpu              = 512
      memory           = 1024
      container_port   = 8000
      desired_count    = 2
      min_capacity     = 2
      max_capacity     = 6
      task_role_arn    = module.iam.ecs_task_role_arns["api-gateway"]
      discoverable     = true
      target_group_arn = module.alb.api_gateway_target_group_arn
      environment = {
        GATEWAY_ORDER_SERVICE_URL     = local.order_service_internal_url
        GATEWAY_INVENTORY_SERVICE_URL = local.inventory_service_internal_url
        GATEWAY_RATE_LIMIT_PER_MINUTE = tostring(var.gateway_rate_limit_per_minute)
      }
      secrets = {
        GATEWAY_DATABASE_URL          = local.database_url_secret_arns["api-gateway"]
        JWT_SECRET_KEY                = module.secrets.jwt_secret_key_secret_arn
        GATEWAY_SEED_ADMIN_PASSWORD   = module.secrets.seed_password_secret_arns["admin"]
        GATEWAY_SEED_OPS_PASSWORD     = module.secrets.seed_password_secret_arns["ops"]
        GATEWAY_SEED_VIEWER_PASSWORD  = module.secrets.seed_password_secret_arns["viewer"]
        GATEWAY_SEED_SERVICE_PASSWORD = module.secrets.seed_password_secret_arns["service"]
      }
    }

    "failure-lab" = {
      image_repo_key = "failure-lab"
      image_tag      = var.image_tag
      cpu            = 512
      memory         = 1024
      container_port = 8000
      desired_count  = 1
      min_capacity   = 1
      max_capacity   = 3
      task_role_arn  = module.iam.ecs_task_role_arns["failure-lab"]
      discoverable   = true
      environment = {
        FAILURE_LAB_API_GATEWAY_URL          = local.gateway_internal_url
        FAILURE_LAB_ORDER_SERVICE_URL        = local.order_service_internal_url
        FAILURE_LAB_INVENTORY_SERVICE_URL    = local.inventory_service_internal_url
        FAILURE_LAB_ORCHESTRATOR_SERVICE_URL = local.orchestrator_internal_url
        FAILURE_LAB_GATEWAY_SERVICE_EMAIL    = "failure-lab-service@omniflow.local"
      }
      secrets = {
        FAILURE_LAB_DATABASE_URL             = local.database_url_secret_arns["failure-lab"]
        JWT_SECRET_KEY                       = module.secrets.jwt_secret_key_secret_arn
        FAILURE_LAB_GATEWAY_SERVICE_PASSWORD = module.secrets.seed_password_secret_arns["service"]
      }
    }

    "failure-lab-poison-consumer" = {
      image_repo_key = "failure-lab"
      image_tag      = var.image_tag
      command        = ["python", "-m", "app.poison_consumer"]
      cpu            = 256
      memory         = 512
      desired_count  = 1
      min_capacity   = 1
      max_capacity   = 2
      task_role_arn  = module.iam.ecs_task_role_arns["failure-lab"]
      discoverable   = false
      environment = {
        KAFKA_BOOTSTRAP_SERVERS = local.msk_bootstrap
        METRICS_PORT            = "9109"
      }
      secrets = {
        FAILURE_LAB_DATABASE_URL = local.database_url_secret_arns["failure-lab"]
      }
    }

    "ops-dashboard" = {
      image_repo_key   = "ops-dashboard"
      image_tag        = var.image_tag
      cpu              = 256
      memory           = 512
      container_port   = 80
      desired_count    = 2
      min_capacity     = 2
      max_capacity     = 4
      task_role_arn    = module.iam.ecs_task_role_arns["ops-dashboard"]
      discoverable     = false
      target_group_arn = module.alb.ops_dashboard_target_group_arn
    }

    # data-platform's lightweight Kafka consumer-group-lag poller — not a
    # Spark job (unlike bronze/silver/gold, which target EMR Serverless
    # instead), so it runs as an always-on ECS Fargate task like every other
    # long-running worker here.
    "lag-poller" = {
      image_repo_key = "data-platform"
      image_tag      = var.image_tag
      command        = ["python", "-m", "app.lag_poller"]
      cpu            = 256
      memory         = 512
      desired_count  = 1
      min_capacity   = 1
      max_capacity   = 1
      task_role_arn  = module.iam.ecs_task_role_arns["data-platform"]
      discoverable   = false
      environment = {
        KAFKA_BOOTSTRAP_SERVERS = local.msk_bootstrap
        DATA_LAKE_BUCKET        = module.s3.bucket_id
      }
    }
  }
}

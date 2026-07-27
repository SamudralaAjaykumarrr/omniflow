# Composes one Secrets Manager secret per service database, each holding a
# full "postgresql+psycopg://user:password@host:port/dbname" connection
# string — matching every service's existing single-DATABASE-URL-env-var
# contract (ORDER_SERVICE_DATABASE_URL, INVENTORY_SERVICE_DATABASE_URL,
# ORCHESTRATOR_DATABASE_URL, GATEWAY_DATABASE_URL, FAILURE_LAB_DATABASE_URL —
# see each service's app/config.py) unchanged, so no application code needs
# to be touched to consume this differently-sourced value.
#
# All five databases share the single RDS instance's one master user/
# password, exactly like the local docker-compose Postgres container (one
# "omniflow" role across every omniflow_* database — see .env.example). The
# five logical databases themselves (omniflow_orders/omniflow_inventory/
# omniflow_orchestrator/omniflow_gateway/omniflow_failure_lab) still need
# the documented manual post-provision step (README's "Post-provision
# manual step") — RDS only creates var.database_name (omniflow_orders) at
# instance-creation time.

locals {
  service_databases = {
    "order-service"            = "omniflow_orders"
    "inventory-service"        = "omniflow_inventory"
    "fulfillment-orchestrator" = "omniflow_orchestrator"
    "api-gateway"              = "omniflow_gateway"
    "failure-lab"              = "omniflow_failure_lab"
  }

  database_urls = {
    for service, dbname in local.service_databases :
    service => "postgresql+psycopg://${module.rds.master_username}:${module.secrets.rds_master_password}@${module.rds.address}:${module.rds.port}/${dbname}"
  }
}

resource "aws_secretsmanager_secret" "database_url" {
  for_each                = local.service_databases
  name                    = "${var.project}-${var.environment}/app/${each.key}-database-url"
  description             = "Full DATABASE_URL connection string for ${each.key}'s database (${each.value})."
  kms_key_id              = module.secrets.kms_key_arn
  recovery_window_in_days = 7

  tags = merge(local.common_tags, {
    Name    = "${var.project}-${var.environment}-${each.key}-database-url"
    Service = each.key
  })
}

resource "aws_secretsmanager_secret_version" "database_url" {
  for_each      = aws_secretsmanager_secret.database_url
  secret_id     = each.value.id
  secret_string = local.database_urls[each.key]
}

locals {
  database_url_secret_arns = { for name, secret in aws_secretsmanager_secret.database_url : name => secret.arn }
}

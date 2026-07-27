# Security groups, scoped so that only the resource that legitimately needs
# to reach another resource can — never a blanket VPC-CIDR or 0.0.0.0/0 rule
# for east-west traffic. Ingress is always "from this specific security
# group", not from a CIDR, everywhere except the ALB's own internet-facing
# listener.

locals {
  name_prefix = "${var.project}-${var.environment}"
}

# --- ALB ---------------------------------------------------------------
resource "aws_security_group" "alb" {
  name_prefix = "${local.name_prefix}-alb-"
  description = "Internet-facing ALB: HTTPS (and HTTP for the redirect) in, anything out."
  vpc_id      = var.vpc_id

  ingress {
    description = "HTTPS from allowed client CIDRs"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = var.alb_ingress_cidrs
  }

  ingress {
    description = "HTTP (redirected to HTTPS by the listener rule, never proxied in plaintext)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = var.alb_ingress_cidrs
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, {
    Name = "${local.name_prefix}-alb-sg"
  })

  lifecycle {
    create_before_destroy = true
  }
}

# --- ECS application services -------------------------------------------
# One shared security group for every ECS service (api-gateway, order-service
# + its workers, inventory-service + its worker, fulfillment-orchestrator +
# its workers, failure-lab + its worker, ops-dashboard). Matches the local
# docker-compose network's actual trust model: every service can already
# reach every other service by hostname on the shared Compose network today,
# so a single shared SG with self-referencing ingress reproduces that
# boundary in AWS rather than inventing a stricter one Phase 11 was never
# asked to design.
resource "aws_security_group" "ecs_service" {
  name_prefix = "${local.name_prefix}-ecs-"
  description = "ECS Fargate application services: ALB -> service on app_port/dashboard_port, service <-> service on app_port."
  vpc_id      = var.vpc_id

  ingress {
    description     = "ALB -> FastAPI services"
    from_port       = var.app_port
    to_port         = var.app_port
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  ingress {
    description     = "ALB -> ops-dashboard (nginx)"
    from_port       = var.dashboard_port
    to_port         = var.dashboard_port
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  ingress {
    description = "Service-to-service REST calls (gateway -> order/inventory, orchestrator -> order/inventory, failure-lab -> gateway/order/inventory/orchestrator) — self-referencing, matches the shared docker-compose network's trust boundary"
    from_port   = var.app_port
    to_port     = var.app_port
    protocol    = "tcp"
    self        = true
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, {
    Name = "${local.name_prefix}-ecs-service-sg"
  })

  lifecycle {
    create_before_destroy = true
  }
}

# --- EMR Serverless (Spark bronze/silver/gold) --------------------------
# EMR Serverless never accepts inbound connections — it only needs egress to
# reach MSK (Kafka source), RDS (not used by Spark today, but harmless to
# omit) and S3 (via the VPC gateway endpoint). This SG exists purely so
# MSK's security group can allow ingress "from this SG" instead of a CIDR.
resource "aws_security_group" "emr_serverless" {
  name_prefix = "${local.name_prefix}-emr-"
  description = "EMR Serverless (Spark bronze/silver/gold) VPC connectivity — egress only, never accepts inbound."
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, {
    Name = "${local.name_prefix}-emr-serverless-sg"
  })

  lifecycle {
    create_before_destroy = true
  }
}

# --- RDS PostgreSQL -------------------------------------------------------
resource "aws_security_group" "rds" {
  name_prefix = "${local.name_prefix}-rds-"
  description = "RDS PostgreSQL: 5432 from ECS application services only."
  vpc_id      = var.vpc_id

  ingress {
    description     = "ECS services -> Postgres"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_service.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, {
    Name = "${local.name_prefix}-rds-sg"
  })

  lifecycle {
    create_before_destroy = true
  }
}

# --- MSK (Kafka, IAM auth) ------------------------------------------------
resource "aws_security_group" "msk" {
  name_prefix = "${local.name_prefix}-msk-"
  description = "MSK: IAM-auth Kafka (9098) and TLS (9094) from ECS services and EMR Serverless only."
  vpc_id      = var.vpc_id

  ingress {
    description     = "ECS services -> MSK (IAM auth)"
    from_port       = 9098
    to_port         = 9098
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_service.id, aws_security_group.emr_serverless.id]
  }

  ingress {
    description     = "ECS services / EMR -> MSK (TLS)"
    from_port       = 9094
    to_port         = 9094
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_service.id, aws_security_group.emr_serverless.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, {
    Name = "${local.name_prefix}-msk-sg"
  })

  lifecycle {
    create_before_destroy = true
  }
}

# --- ElastiCache Redis -----------------------------------------------------
# Modeled for the documented next step in RISKS.md #13 (a shared backing
# store for a horizontally-scaled gateway's rate limiter) — not yet consumed
# by any application code, since the app itself still uses an in-process
# limiter today.
resource "aws_security_group" "elasticache" {
  name_prefix = "${local.name_prefix}-cache-"
  description = "ElastiCache Redis: 6379 from ECS application services only."
  vpc_id      = var.vpc_id

  ingress {
    description     = "ECS services -> Redis"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_service.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, {
    Name = "${local.name_prefix}-elasticache-sg"
  })

  lifecycle {
    create_before_destroy = true
  }
}

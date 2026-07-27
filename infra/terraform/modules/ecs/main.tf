# ECS Fargate cluster hosting every application-tier deployable (see
# var.services' description). One shared cluster, one Cloud Map private DNS
# namespace so the 5 FastAPI services remain reachable by a stable hostname
# from every other service — reproducing docker-compose's own embedded-DNS
# "call it by service name" convenience (e.g. inventory-service:8000) inside
# a real VPC, rather than requiring every caller to look up a dynamic IP or
# route everything back out through the ALB.

locals {
  name_prefix           = "${var.project}-${var.environment}"
  discoverable_services = { for name, svc in var.services : name => svc if svc.discoverable }
}

data "aws_region" "current" {}

resource "aws_ecs_cluster" "this" {
  name = "${local.name_prefix}-cluster"

  setting {
    name  = "containerInsights"
    value = var.container_insights_enabled ? "enabled" : "disabled"
  }

  tags = merge(var.tags, {
    Name = "${local.name_prefix}-cluster"
  })
}

resource "aws_ecs_cluster_capacity_providers" "this" {
  cluster_name       = aws_ecs_cluster.this.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
    base              = 1
  }
}

resource "aws_service_discovery_private_dns_namespace" "this" {
  name        = "${var.project}-${var.environment}.local"
  description = "Internal service discovery for ${local.name_prefix} — reproduces docker-compose's embedded-DNS 'call it by service name' convenience in AWS."
  vpc         = var.vpc_id

  tags = var.tags
}

resource "aws_service_discovery_service" "this" {
  for_each = local.discoverable_services
  name     = each.key

  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.this.id

    dns_records {
      ttl  = 10
      type = "A"
    }

    routing_policy = "MULTIVALUE"
  }

  health_check_custom_config {
    failure_threshold = 1
  }

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "this" {
  for_each          = var.services
  name              = "/ecs/${local.name_prefix}/${each.key}"
  retention_in_days = var.log_retention_days

  tags = merge(var.tags, {
    Service = each.key
  })
}

locals {
  container_definitions = {
    for name, svc in var.services : name => [merge(
      {
        name      = name
        image     = "${var.ecr_repository_urls[svc.image_repo_key]}:${svc.image_tag}"
        essential = true

        environment = [for k, v in svc.environment : { name = k, value = v }]
        secrets     = [for k, arn in svc.secrets : { name = k, valueFrom = arn }]

        logConfiguration = {
          logDriver = "awslogs"
          options = {
            "awslogs-group"         = aws_cloudwatch_log_group.this[name].name
            "awslogs-region"        = data.aws_region.current.name
            "awslogs-stream-prefix" = name
          }
        }
      },
      svc.command != null ? { command = svc.command } : {},
      svc.container_port != null ? { portMappings = [{ containerPort = svc.container_port, protocol = "tcp" }] } : {},
    )]
  }
}

resource "aws_ecs_task_definition" "this" {
  for_each                 = var.services
  family                   = "${local.name_prefix}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = each.value.cpu
  memory                   = each.value.memory
  execution_role_arn       = var.task_execution_role_arn
  task_role_arn            = each.value.task_role_arn
  container_definitions    = jsonencode(local.container_definitions[each.key])

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  tags = merge(var.tags, {
    Service = each.key
  })
}

resource "aws_ecs_service" "this" {
  for_each        = var.services
  name            = "${local.name_prefix}-${each.key}"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.this[each.key].arn
  desired_count   = each.value.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.security_group_id]
    assign_public_ip = false
  }

  dynamic "load_balancer" {
    for_each = each.value.target_group_arn != null ? [each.value.target_group_arn] : []
    content {
      target_group_arn = load_balancer.value
      container_name   = each.key
      container_port   = each.value.container_port
    }
  }

  dynamic "service_registries" {
    for_each = each.value.discoverable ? [aws_service_discovery_service.this[each.key].arn] : []
    content {
      registry_arn = service_registries.value
    }
  }

  health_check_grace_period_seconds = each.value.target_group_arn != null ? 60 : null

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  enable_execute_command = true

  tags = merge(var.tags, {
    Service = each.key
  })

  lifecycle {
    ignore_changes = [desired_count] # autoscaling owns this after initial apply
  }
}

# --- Autoscaling: CPU target tracking, per service ---------------------------
resource "aws_appautoscaling_target" "this" {
  for_each           = var.services
  service_namespace  = "ecs"
  resource_id        = "service/${aws_ecs_cluster.this.name}/${aws_ecs_service.this[each.key].name}"
  scalable_dimension = "ecs:service:DesiredCount"
  min_capacity       = coalesce(each.value.min_capacity, each.value.desired_count)
  max_capacity       = coalesce(each.value.max_capacity, each.value.desired_count * 3)
}

resource "aws_appautoscaling_policy" "cpu" {
  for_each           = var.services
  name               = "${local.name_prefix}-${each.key}-cpu-target-tracking"
  service_namespace  = aws_appautoscaling_target.this[each.key].service_namespace
  resource_id        = aws_appautoscaling_target.this[each.key].resource_id
  scalable_dimension = aws_appautoscaling_target.this[each.key].scalable_dimension
  policy_type        = "TargetTrackingScaling"

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value       = 60
    scale_in_cooldown  = 120
    scale_out_cooldown = 60
  }
}

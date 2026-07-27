# One internet-facing ALB, host-based routing: the default action is
# api-gateway (the customer-facing entry point in every existing diagram —
# docs/architecture.md's AWS deployment target and system-context.md's trust
# boundary both name the ALB as fronting the gateway); a Host-header rule
# routes ops-dashboard traffic to its own target group. order-service,
# inventory-service, fulfillment-orchestrator, and failure-lab are
# deliberately NOT reachable through this ALB — matching the same posture
# RISKS.md #25/#34 already established locally (those services' own HTTP
# routes stay internal-only; only the two ADR-0009-named/dashboard-fronting
# surfaces are internet-facing), not a new restriction invented for the
# cloud target.

locals {
  name_prefix = "${var.project}-${var.environment}"
}

resource "aws_lb" "this" {
  name                       = "${local.name_prefix}-alb"
  internal                   = false
  load_balancer_type         = "application"
  security_groups            = [var.security_group_id]
  subnets                    = var.public_subnet_ids
  idle_timeout               = var.idle_timeout_seconds
  enable_deletion_protection = var.deletion_protection
  enable_http2               = true
  drop_invalid_header_fields = true

  tags = merge(var.tags, {
    Name = "${local.name_prefix}-alb"
  })
}

resource "aws_lb_target_group" "api_gateway" {
  name        = "${local.name_prefix}-api-gateway-tg"
  port        = var.app_port
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip" # Fargate tasks have no EC2 instance ID to register by

  health_check {
    enabled             = true
    path                = var.api_gateway_health_check_path
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  deregistration_delay = 30

  tags = merge(var.tags, {
    Name    = "${local.name_prefix}-api-gateway-tg"
    Service = "api-gateway"
  })
}

resource "aws_lb_target_group" "ops_dashboard" {
  name        = "${local.name_prefix}-ops-dashboard-tg"
  port        = var.dashboard_port
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    enabled             = true
    path                = var.ops_dashboard_health_check_path
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  deregistration_delay = 30

  tags = merge(var.tags, {
    Name    = "${local.name_prefix}-ops-dashboard-tg"
    Service = "ops-dashboard"
  })
}

resource "aws_lb_listener" "http_redirect" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"

    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.this.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api_gateway.arn
  }
}

resource "aws_lb_listener_rule" "ops_dashboard" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.ops_dashboard.arn
  }

  condition {
    host_header {
      values = [var.dashboard_hostname]
    }
  }
}

# One ECR repository per deployable application image, mirroring
# `make docker-build`'s existing list (order-service, inventory-service,
# fulfillment-orchestrator, api-gateway, data-platform, ops-dashboard,
# failure-lab). event-contracts has no image of its own locally (installed
# as a local dependency into the other five's builds) and gets none here
# either, for the same reason.

locals {
  name_prefix = "${var.project}-${var.environment}"
}

resource "aws_kms_key" "ecr" {
  description         = "KMS key encrypting ${local.name_prefix} ECR repositories at rest."
  enable_key_rotation = true

  tags = merge(var.tags, {
    Name = "${local.name_prefix}-ecr-kms"
  })
}

resource "aws_kms_alias" "ecr" {
  name          = "alias/${local.name_prefix}-ecr"
  target_key_id = aws_kms_key.ecr.key_id
}

resource "aws_ecr_repository" "this" {
  for_each             = toset(var.repository_names)
  name                 = "${local.name_prefix}/${each.value}"
  image_tag_mutability = var.image_tag_mutability

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.ecr.arn
  }

  tags = merge(var.tags, {
    Name    = "${local.name_prefix}-${each.value}"
    Service = each.value
  })
}

resource "aws_ecr_lifecycle_policy" "this" {
  for_each   = aws_ecr_repository.this
  repository = each.value.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after ${var.untagged_image_expiry_days} days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = var.untagged_image_expiry_days
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Keep only the most recent ${var.max_tagged_images_per_repo} tagged images"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["v", "sha-", "latest"]
          countType     = "imageCountMoreThan"
          countNumber   = var.max_tagged_images_per_repo
        }
        action = { type = "expire" }
      },
    ]
  })
}

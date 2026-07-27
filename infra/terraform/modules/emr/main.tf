# EMR Serverless — the cloud target ADR 0005 itself names ("EMR or
# Kubernetes-based Spark") for services/data-platform's bronze/silver/gold
# jobs, which run in `local[*]` mode locally. Serverless (over EMR-on-EC2)
# is chosen specifically because this workload is bursty/periodic (batch
# backfills, restartable streaming jobs), not an always-on cluster — it
# scales to zero and bills per vCPU/memory-second actually used, with no
# cluster to size, patch, or leave idling between runs.
#
# Terraform manages the persistent "application" shell only. Submitting an
# actual job run (spark-submit equivalent) is an operator/CI action against
# the running application via the AWS CLI/SDK, not a Terraform resource —
# consistent with this phase's scope (author + validate infrastructure,
# never invoke it).

locals {
  name_prefix = "${var.project}-${var.environment}"
}

data "aws_iam_policy_document" "emr_serverless_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["emr-serverless.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "emr_execution" {
  name               = "${local.name_prefix}-emr-serverless-execution"
  assume_role_policy = data.aws_iam_policy_document.emr_serverless_assume_role.json
  tags               = var.tags
}

locals {
  msk_arn_parts    = split(":", var.msk_cluster_arn)
  msk_region       = local.msk_arn_parts[3]
  msk_account_id   = local.msk_arn_parts[4]
  msk_cluster_path = replace(local.msk_arn_parts[5], "cluster/", "")
  msk_topic_arn    = "arn:aws:kafka:${local.msk_region}:${local.msk_account_id}:topic/${local.msk_cluster_path}/*"
  msk_group_arn    = "arn:aws:kafka:${local.msk_region}:${local.msk_account_id}:group/${local.msk_cluster_path}/*"
}

data "aws_iam_policy_document" "emr_execution" {
  statement {
    sid       = "DataLakeReadWrite"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
    resources = [var.s3_bucket_arn, "${var.s3_bucket_arn}/*"]
  }

  statement {
    sid       = "DataLakeKmsUse"
    effect    = "Allow"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [var.s3_kms_key_arn]
  }

  statement {
    sid       = "MSKConnect"
    effect    = "Allow"
    actions   = ["kafka-cluster:Connect", "kafka-cluster:DescribeCluster"]
    resources = [var.msk_cluster_arn]
  }

  statement {
    sid       = "MSKTopicRead"
    effect    = "Allow"
    actions   = ["kafka-cluster:DescribeTopic", "kafka-cluster:ReadData"]
    resources = [local.msk_topic_arn]
  }

  statement {
    sid       = "MSKConsumerGroup"
    effect    = "Allow"
    actions   = ["kafka-cluster:AlterGroup", "kafka-cluster:DescribeGroup"]
    resources = [local.msk_group_arn]
  }

  statement {
    sid       = "EmrLogging"
    effect    = "Allow"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogGroups", "logs:DescribeLogStreams"]
    resources = ["arn:aws:logs:*:*:log-group:/${var.project}/${var.environment}/emr*"]
  }
}

resource "aws_iam_role_policy" "emr_execution" {
  name   = "${local.name_prefix}-emr-serverless-execution"
  role   = aws_iam_role.emr_execution.id
  policy = data.aws_iam_policy_document.emr_execution.json
}

resource "aws_cloudwatch_log_group" "emr" {
  name              = "/${var.project}/${var.environment}/emr-serverless"
  retention_in_days = 30

  tags = var.tags
}

resource "aws_emrserverless_application" "spark" {
  name          = "${local.name_prefix}-spark-bronze-silver-gold"
  release_label = var.release_label
  type          = "SPARK"

  network_configuration {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [var.security_group_id]
  }

  maximum_capacity {
    cpu    = var.max_capacity_cpu
    memory = var.max_capacity_memory_gb
  }

  dynamic "initial_capacity" {
    for_each = var.pre_init_capacity_cpu > 0 ? [1] : []
    content {
      initial_capacity_type = "Driver"
      initial_capacity_config {
        worker_count = 1
        worker_configuration {
          cpu    = "${var.pre_init_capacity_cpu} vCPU"
          memory = "${var.pre_init_capacity_cpu * 4} GB"
        }
      }
    }
  }

  auto_start_configuration {
    enabled = true
  }

  auto_stop_configuration {
    enabled              = true
    idle_timeout_minutes = var.idle_timeout_minutes
  }

  tags = merge(var.tags, {
    Name = "${local.name_prefix}-spark-application"
  })
}

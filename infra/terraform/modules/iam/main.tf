# Two distinct role shapes, matching ECS Fargate's own execution-role vs.
# task-role split:
#   - Task-execution role (shared): what ECS itself needs to launch a
#     container — pull the image from ECR, write logs to CloudWatch, and
#     resolve any "secrets" block in the container definition into plain
#     env vars at container start. The running application code never
#     calls Secrets Manager itself for these.
#   - Task role (one per service): what the *application code inside the
#     container* is allowed to call via the AWS SDK at runtime — here,
#     MSK IAM-auth Kafka client permissions for the services that actually
#     produce/consume (order-service, inventory-service,
#     fulfillment-orchestrator, failure-lab). api-gateway and
#     ops-dashboard get a task role with no attached policy — present for
#     consistency/future extension, not because they need AWS API access
#     today.

locals {
  name_prefix = "${var.project}-${var.environment}"

  msk_arn_parts    = split(":", var.msk_cluster_arn)
  msk_region       = local.msk_arn_parts[3]
  msk_account_id   = local.msk_arn_parts[4]
  msk_cluster_path = replace(local.msk_arn_parts[5], "cluster/", "")
  msk_topic_arn    = "arn:aws:kafka:${local.msk_region}:${local.msk_account_id}:topic/${local.msk_cluster_path}/*"
  msk_group_arn    = "arn:aws:kafka:${local.msk_region}:${local.msk_account_id}:group/${local.msk_cluster_path}/*"

  kafka_service_set = toset(var.ecs_service_names_needing_kafka)
}

data "aws_iam_policy_document" "ecs_tasks_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# --- Shared task-execution role ---------------------------------------------
resource "aws_iam_role" "ecs_task_execution" {
  name               = "${local.name_prefix}-ecs-task-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume_role.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution_managed" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "ecs_task_execution_secrets" {
  statement {
    sid       = "ReadContainerSecrets"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = var.secret_arns_for_execution_role
  }

  statement {
    sid       = "DecryptContainerSecrets"
    effect    = "Allow"
    actions   = ["kms:Decrypt"]
    resources = var.kms_key_arns_for_execution_role
  }
}

resource "aws_iam_role_policy" "ecs_task_execution_secrets" {
  name   = "${local.name_prefix}-ecs-task-execution-secrets"
  role   = aws_iam_role.ecs_task_execution.id
  policy = data.aws_iam_policy_document.ecs_task_execution_secrets.json
}

# --- Per-service task roles --------------------------------------------------
resource "aws_iam_role" "ecs_task" {
  for_each           = toset(var.ecs_service_names)
  name               = "${local.name_prefix}-${each.value}-task-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume_role.json

  tags = merge(var.tags, {
    Service = each.value
  })
}

data "aws_iam_policy_document" "msk_client" {
  statement {
    sid       = "MSKConnect"
    effect    = "Allow"
    actions   = ["kafka-cluster:Connect", "kafka-cluster:DescribeCluster"]
    resources = [var.msk_cluster_arn]
  }

  statement {
    sid       = "MSKTopicReadWrite"
    effect    = "Allow"
    actions   = ["kafka-cluster:DescribeTopic", "kafka-cluster:ReadData", "kafka-cluster:WriteData"]
    resources = [local.msk_topic_arn]
  }

  statement {
    sid       = "MSKConsumerGroup"
    effect    = "Allow"
    actions   = ["kafka-cluster:AlterGroup", "kafka-cluster:DescribeGroup"]
    resources = [local.msk_group_arn]
  }
}

resource "aws_iam_role_policy" "msk_client" {
  for_each = local.kafka_service_set
  name     = "${local.name_prefix}-${each.value}-msk-client"
  role     = aws_iam_role.ecs_task[each.value].id
  policy   = data.aws_iam_policy_document.msk_client.json
}

data "aws_iam_policy_document" "s3_data_lake_client" {
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
}

resource "aws_iam_role_policy" "s3_data_lake_client" {
  for_each = toset(var.ecs_service_names_needing_s3)
  name     = "${local.name_prefix}-${each.value}-s3-data-lake-client"
  role     = aws_iam_role.ecs_task[each.value].id
  policy   = data.aws_iam_policy_document.s3_data_lake_client.json
}

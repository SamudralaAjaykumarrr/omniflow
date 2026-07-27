# MSK (managed Kafka) replacing the local single-broker Redpanda service —
# Redpanda is Kafka-protocol-compatible (ADR 0001), so the same
# event-contracts producer/consumer code (confluent-kafka client) targets
# MSK unchanged; only KAFKA_BOOTSTRAP_SERVERS and the IAM-auth SASL
# mechanism differ from local dev's PLAINTEXT connection.

locals {
  name_prefix  = "${var.project}-${var.environment}"
  broker_count = coalesce(var.broker_count, length(var.private_subnet_ids))
}

resource "aws_kms_key" "msk" {
  description         = "KMS key encrypting the ${local.name_prefix} MSK cluster (storage) at rest."
  enable_key_rotation = true

  tags = merge(var.tags, {
    Name = "${local.name_prefix}-msk-kms"
  })
}

resource "aws_kms_alias" "msk" {
  name          = "alias/${local.name_prefix}-msk"
  target_key_id = aws_kms_key.msk.key_id
}

resource "aws_cloudwatch_log_group" "msk_broker_logs" {
  name              = "/${var.project}/${var.environment}/msk/broker-logs"
  retention_in_days = var.cloudwatch_log_retention_days

  tags = var.tags
}

resource "aws_msk_configuration" "this" {
  name           = "${local.name_prefix}-msk-config"
  kafka_versions = [var.kafka_version]

  server_properties = <<-PROPERTIES
    auto.create.topics.enable=false
    default.replication.factor=${var.default_replication_factor}
    num.partitions=${var.num_partitions_default}
    log.retention.hours=${var.log_retention_hours}
    min.insync.replicas=2
  PROPERTIES
}

resource "aws_msk_cluster" "this" {
  cluster_name           = "${local.name_prefix}-msk"
  kafka_version          = var.kafka_version
  number_of_broker_nodes = local.broker_count

  configuration_info {
    arn      = aws_msk_configuration.this.arn
    revision = aws_msk_configuration.this.latest_revision
  }

  broker_node_group_info {
    instance_type   = var.broker_instance_type
    client_subnets  = var.private_subnet_ids
    security_groups = [var.security_group_id]

    storage_info {
      ebs_storage_info {
        volume_size = var.broker_ebs_volume_size_gb
      }
    }
  }

  encryption_info {
    encryption_at_rest_kms_key_arn = aws_kms_key.msk.arn

    encryption_in_transit {
      client_broker = "TLS"
      in_cluster    = true
    }
  }

  client_authentication {
    sasl {
      iam = true
    }
  }

  logging_info {
    broker_logs {
      cloudwatch_logs {
        enabled   = true
        log_group = aws_cloudwatch_log_group.msk_broker_logs.name
      }
    }
  }

  enhanced_monitoring = "PER_TOPIC_PER_BROKER"

  tags = merge(var.tags, {
    Name = "${local.name_prefix}-msk"
  })

  lifecycle {
    precondition {
      condition     = local.broker_count % length(var.private_subnet_ids) == 0
      error_message = "broker_count must be a whole multiple of the number of private subnets supplied."
    }
  }
}

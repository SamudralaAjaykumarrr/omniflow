output "cluster_arn" {
  description = "ARN of the MSK cluster, for IAM policy scoping (kafka-cluster:* actions)."
  value       = aws_msk_cluster.this.arn
}

output "cluster_name" {
  description = "MSK cluster name (for CloudWatch dimension / alarm wiring)."
  value       = aws_msk_cluster.this.cluster_name
}

output "bootstrap_brokers_sasl_iam" {
  description = "IAM-auth bootstrap broker connection string — what KAFKA_BOOTSTRAP_SERVERS should be set to for every producer/consumer."
  value       = aws_msk_cluster.this.bootstrap_brokers_sasl_iam
}

output "bootstrap_brokers_tls" {
  description = "TLS (non-IAM) bootstrap broker connection string, for tooling that only supports TLS client auth."
  value       = aws_msk_cluster.this.bootstrap_brokers_tls
}

output "zookeeper_connect_string" {
  description = "ZooKeeper connection string (legacy clients only; this cluster's own client auth is IAM, not ZK-based)."
  value       = aws_msk_cluster.this.zookeeper_connect_string
}

output "vpc_id" {
  description = "ID of the created VPC."
  value       = aws_vpc.this.id
}

output "vpc_cidr" {
  description = "CIDR block of the created VPC (used by security-group modules for VPC-internal ingress rules)."
  value       = var.vpc_cidr
}

output "public_subnet_ids" {
  description = "IDs of the public subnets (ALB, NAT gateways)."
  value       = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "IDs of the private subnets (ECS tasks, RDS, MSK, ElastiCache, EMR Serverless)."
  value       = aws_subnet.private[*].id
}

output "nat_gateway_ids" {
  description = "IDs of the NAT gateway(s)."
  value       = aws_nat_gateway.this[*].id
}

output "vpc_endpoints_security_group_id" {
  description = "Security group attached to the interface VPC endpoints."
  value       = aws_security_group.vpc_endpoints.id
}

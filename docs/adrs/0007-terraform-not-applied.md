# ADR 0007: AWS Infrastructure — Terraform Authored and Validated, Never Applied

## Status
Accepted

## Context
The spec asks for cloud-ready Terraform (ECS Fargate/EKS, RDS, ElastiCache,
MSK-or-justified-alternative, S3, CloudWatch, IAM, Secrets Manager, ALB) but
also explicitly forbids automatic deployment or incurring cloud charges, and
this session has no AWS credentials and will not request or use any. Applying
real infrastructure is also flagged by this session's own standing safety
rules as something to pause and confirm before doing, given it is an
externally-visible, cost-incurring, hard-to-fully-reverse action.

## Decision
Author complete, realistic Terraform under `infra/terraform/` targeting the
services listed above, with environment separation (e.g. `envs/dev`,
`envs/prod` or workspaces) and remote-state guidance documented but not wired
to a real backend/bucket. Validate it locally with `terraform fmt -check` and
`terraform validate` run inside the official `hashicorp/terraform` Docker
image (no host Terraform install, no credentials, no network calls to AWS
beyond provider-schema resolution which `validate` itself may need — if that
requires network access it is called out plainly in the docs, not hidden).
Never run `terraform plan` against a real account or `terraform apply`.

## Consequences
- The IaC is inspectable and demonstrates real AWS architecture judgment
  (least-privilege IAM, managed-service choices, network layout) without any
  cost or credential exposure.
- `docs/architecture.md`'s AWS deployment diagram and this Terraform must stay
  in sync — checked during the Phase 11/13 documentation pass.
- If the user later wants to actually deploy this, that is a separate,
  explicit, credentialed decision outside this project's autonomous scope —
  called out in `infra/terraform/README.md` (cost considerations and
  destroy instructions included there per the spec).

## Alternatives considered
- **Deploy to a free-tier AWS account for a live demo**: rejected outright —
  requires credentials this session doesn't have and shouldn't request
  autonomously, and risks real charges the moment anything falls outside
  free-tier bounds (NAT gateways, MSK, RDS are generally not free-tier
  eligible at all).
- **Skip Terraform entirely, just describe the architecture in prose**:
  rejected — the spec asks for actual IaC, and "authored + validated, not
  applied" is the honest middle ground that satisfies both the deliverable
  and the no-cloud-spend constraint.

# OmniFlow — AWS Infrastructure (Terraform)

Phase 11 deliverable. Per [ADR 0007](../../docs/adrs/0007-terraform-not-applied.md),
this Terraform is **authored and validated only — it has never been planned
or applied against a real AWS account, no AWS credentials were used to
write it, and no AWS API call of any kind was made while writing it.** If
you want to actually deploy this, that is a separate, explicit, credentialed
decision — read "Deployment warnings" below first.

## Architecture

Maps the running `docker-compose.yml` stack onto managed AWS services,
consistent with `docs/architecture.md`'s AWS deployment diagram:

| Local (docker-compose.yml) | AWS |
|---|---|
| `postgres` (5 logical databases) | RDS PostgreSQL, single instance |
| `redpanda` | MSK (IAM-auth Kafka) |
| `minio` | S3 (one data-lake bucket, same prefix layout) |
| `spark-bronze`/`spark-silver`/`spark-gold` | EMR Serverless (Spark application) |
| `lag-poller` | ECS Fargate task (not a Spark job — unaffected by the EMR move) |
| `api-gateway`, `order-service` (+ validator-consumer, outbox-relay), `inventory-service` (+ outbox-relay), `fulfillment-orchestrator` (+ consumer, outbox-relay), `failure-lab` (+ poison-consumer), `ops-dashboard` | ECS Fargate services, one cluster |
| Docker embedded DNS (`http://order-service:8000`) | Cloud Map private DNS namespace (`order-service.<project>-<env>.local`) |
| `prometheus`/`grafana`/`jaeger` | CloudWatch Logs/Metrics/Alarms/Dashboard (see "Observability", below — this is a deliberate change of tool, not a 1:1 port) |
| In-process gateway rate limiter (`RISKS.md` #13) | ElastiCache Redis — modeled, not yet consumed by application code |

Only **api-gateway** and **ops-dashboard** are reachable through the ALB
(host-based routing: everything except `dashboard_hostname`'s Host header
goes to api-gateway). order-service, inventory-service,
fulfillment-orchestrator, and failure-lab stay internal-only — the same
posture `RISKS.md` #25/#34 already established for the local dashboard's
direct-proxy paths, not a new restriction invented for this phase.

```
Internet
   |
   v
  ALB (HTTPS, host-based routing)
   |-- default -> api-gateway (ECS Fargate, target group)
   `-- Host: <dashboard_hostname> -> ops-dashboard (ECS Fargate, target group)

  Cloud Map private DNS namespace (<project>-<env>.local)
   order-service, inventory-service, fulfillment-orchestrator,
   api-gateway, failure-lab  <-- discoverable by every other ECS service

  RDS PostgreSQL  <-- api-gateway, order-service, inventory-service,
                      fulfillment-orchestrator, failure-lab (each its
                      own database, one shared master user)
  MSK (IAM auth)  <-- every Kafka-touching service/worker + EMR Serverless
  S3 data lake    <-- EMR Serverless (Bronze/Silver/Gold), lag-poller
  EMR Serverless  <-- Spark bronze/silver/gold jobs (submitted manually,
                      never by this Terraform — see "EMR Serverless", below)
```

## Prerequisites

- Docker (for running Terraform via the official image — no host Terraform
  install, matching this repo's "no host toolchain" convention, see
  `CLAUDE.md`).
- Nothing else. No AWS CLI, no AWS credentials, no AWS account is needed to
  run any of the validation commands below.

## Validation commands (no credentials, no AWS API calls, no cost)

Run from the repo root:

```bash
make tf-fmt-check   # terraform fmt -check -recursive
make tf-init         # terraform init -backend=false, every module + environment
make tf-validate     # terraform validate, every module + environment
make tf-validate-all # fmt-check + init + validate, in that order
```

Each target runs the official `hashicorp/terraform` Docker image
(`hashicorp/terraform:1.9`), bind-mounting only `infra/terraform/`. `init
-backend=false` and `validate` do not require AWS credentials and make no
call to any AWS API. `terraform init` **does** reach out to
`registry.terraform.io` over the network to download the `aws`/`random`
provider plugins (not AWS itself) — called out here plainly, per ADR 0007's
own instruction, rather than silently assumed to be fully offline. Once
downloaded, `terraform validate`'s own schema/type/reference checking needs
no further network access.

**Never run** `terraform plan` (against a real account) or `terraform
apply`/`destroy` from this repository. Nothing in this repo's Makefile does
either.

## Deployment warnings

This Terraform has never been deployed. If you choose to deploy it
yourself (a decision entirely your own, outside this project's scope):

1. **Read `docs/adrs/0007-terraform-not-applied.md` first.**
2. You will need a real AWS account, real credentials, and to accept real
   cost (see "Cost considerations" below).
3. Fill in `environments/<env>/terraform.tfvars` (copy from
   `terraform.tfvars.example` — **never commit a real tfvars file**;
   `.gitignore` already excludes real `*.tfvars`).
4. An ACM certificate must already exist and be validated against a domain
   you own — this Terraform does not create a Route 53 zone or request a
   certificate.
5. Run `terraform init` (with a real backend configured — see
   `backend.tf`'s comments) and `terraform plan` yourself, review every
   resource it proposes, then `terraform apply` only if you're satisfied.
6. See "Known limitations and required follow-ups" below for what does
   **not** work out of the box after `apply` — this Terraform authors a
   realistic target shape, not a proven, end-to-end-tested deployment.
7. To tear down: `terraform destroy` (after disabling `deletion_protection`
   on RDS and the ALB, which default to blocking exactly this).

## Terraform module structure

```
infra/terraform/
  modules/
    networking/      VPC, public/private subnets x2+ AZ, IGW, NAT gateway(s),
                      S3 gateway endpoint, ECR/Secrets Manager/CloudWatch
                      Logs interface endpoints
    security/        Security groups (ALB, ECS services, RDS, MSK,
                      ElastiCache, EMR Serverless) — ingress always scoped
                      to a specific source security group, never a CIDR,
                      except the ALB's own internet-facing listener
    ecr/              7 repositories (one per services/<name> image),
                      scan-on-push, KMS encryption, lifecycle policy
    iam/              Shared ECS task-execution role; one task role per
                      logical service group (MSK IAM-auth client
                      permissions only for the services/workers that
                      actually touch Kafka; S3 permissions only for
                      data-platform's lag-poller)
    secrets/          Secrets Manager: JWT signing secret, seeded demo-user
                      passwords, RDS master password — every value
                      generated by Terraform's own `random` provider, never
                      read from a tfvars file
    rds/               Single PostgreSQL instance, Multi-AZ toggle,
                      encryption at rest, automated backups, enhanced
                      monitoring, Performance Insights
    elasticache/      Redis replication group — modeled for the documented
                      next step in `RISKS.md` #13, not yet consumed by app code
    msk/              MSK cluster, IAM auth, encryption in transit/at rest
    s3/                Data-lake bucket (bronze/bronze_rejects/silver/
                      silver_rejects/late_events/gold/checkpoints/
                      dq-reports/forecasting — same prefixes as
                      `infra/docker/minio/create-buckets.sh`), versioning,
                      lifecycle tiering, TLS-only bucket policy
    alb/              ALB, HTTPS listener (ACM cert), HTTP->HTTPS redirect,
                      host-based routing to api-gateway/ops-dashboard
    ecs/              Fargate cluster, Cloud Map namespace, one task
                      definition + service per deployable (13 total),
                      CloudWatch log groups, CPU-target-tracking autoscaling
    emr/              EMR Serverless application (Spark bronze/silver/gold),
                      its own execution role (S3 + MSK IAM-auth)
    observability/    CloudWatch alarms (ALB 5xx, ECS CPU/memory, RDS
                      CPU/free storage, MSK broker disk), an SNS topic, one
                      CloudWatch dashboard
  environments/
    dev/              Cost-optimized sizing: single NAT gateway, 2 AZs,
                      burstable/Graviton instance classes, no Multi-AZ
    prod/              HA-oriented sizing: NAT gateway per AZ, 3 AZs,
                      Multi-AZ RDS, ElastiCache automatic failover, larger
                      instance classes, higher ECS desired-count/min/max —
                      see environments/prod/variables.tf's defaults for the
                      exact deltas from dev
  README.md           This file
```

Each environment's `main.tf` wires every module together; `services.tf`
builds the map of all 13 ECS deployables (mirroring `docker-compose.yml`'s
own service list); `database_secrets.tf` composes one
`postgresql+psycopg://...` connection-string secret per service database
from the single RDS master user/password (matching the local Postgres
container's own "one role across every `omniflow_*` database" convention —
see `.env.example`).

## Service -> AWS resource mapping (exact)

| ECS logical service (shared IAM task role) | ECS deployables | AWS image | Discoverable via Cloud Map | Behind ALB |
|---|---|---|---|---|
| order-service | order-service (API), order-validator-consumer, order-outbox-relay | `order-service` | order-service only | no |
| inventory-service | inventory-service (API), inventory-outbox-relay | `inventory-service` | inventory-service only | no |
| fulfillment-orchestrator | fulfillment-orchestrator (API), -consumer, -outbox-relay | `fulfillment-orchestrator` | fulfillment-orchestrator only | no |
| failure-lab | failure-lab (API), failure-lab-poison-consumer | `failure-lab` | failure-lab only | no |
| api-gateway | api-gateway | `api-gateway` | yes | **yes** (default Host) |
| ops-dashboard | ops-dashboard | `ops-dashboard` | no | **yes** (`dashboard_hostname` Host) |
| data-platform | lag-poller (ECS) + Spark bronze/silver/gold (EMR Serverless, separate from ECS) | `data-platform` | no | no |

## IAM and secret-management strategy

- **Task-execution role** (shared, one per environment): ECR image pull,
  CloudWatch log write, and `secretsmanager:GetSecretValue` +
  `kms:Decrypt` scoped to exactly the secret/KMS-key ARNs each container
  definition's `secrets` block references — this is what resolves a
  secret into a plain env var at container start; the running application
  code itself never calls Secrets Manager for these.
- **Task roles** (one per logical service group): only the
  Kafka-producing/consuming services get MSK IAM-auth `kafka-cluster:*`
  permissions, scoped to this cluster's own topic/group ARN patterns; only
  `data-platform` (lag-poller) gets S3 permissions, scoped to the data-lake
  bucket; `api-gateway`/`ops-dashboard` get an otherwise-empty task role.
- **EMR Serverless execution role** (separate, in `modules/emr`): S3
  read/write on the data-lake bucket + its KMS key, MSK IAM-auth
  read-only-plus-consumer-group permissions, CloudWatch Logs write.
- Every secret value (JWT signing key, seeded demo-account passwords, RDS
  master password) is generated by Terraform's own `random` provider at
  apply time — never a literal value in a tfvars file, matching this
  repo's standing "no hardcoded secrets" rule.

## Observability strategy

CloudWatch (Logs, Metrics, Alarms, one dashboard) is the cloud target's
observability backend — matching `docs/architecture.md`'s own AWS
deployment diagram, which names CloudWatch, not Jaeger/Prometheus/Grafana.
Those three stay local-demo-only self-hosted tools; this is a deliberate
change of observability *tool* for the cloud target, not a claim that
Jaeger/Prometheus/Grafana were "ported" to AWS. See "Known limitations"
below for what this means for distributed tracing specifically.

Alarms: ALB 5xx count, ECS service CPU/memory (per service), RDS CPU/free
storage, MSK broker disk usage — all publish to one SNS topic
(`var.alarm_email`, optional; a real email subscription requires clicking
an AWS-sent confirmation link, which Terraform cannot do for you).

## Scaling and availability design

- ECS: CPU-target-tracking autoscaling per service (default target 60%),
  `min_capacity`/`max_capacity` set per service in `services.tf` (dev:
  1-3 for internal services, 2-6 for api-gateway; prod: 2-4/3-8).
- RDS: `multi_az` toggle (dev: false, prod: true), storage autoscaling up
  to `max_allocated_storage_gb`.
- MSK: broker count is a whole multiple of the AZ count (dev: 2 brokers/2
  AZs; prod: 3 brokers/3 AZs).
- ALB: spans every public subnet (2 AZs dev, 3 AZs prod); health checks
  against each service's real `/healthz` (api-gateway) or `/` (ops-dashboard).
- EMR Serverless: auto-scales per job run natively (no capacity to size),
  auto-stops after `idle_timeout_minutes` of no running job — the whole
  point of choosing Serverless over an always-on EMR-on-EC2 cluster for a
  bursty batch/streaming-restart workload (ADR 0005).

## Cost drivers if this were ever deployed

Nothing below has been incurred — this Terraform has never been applied.
Listed so a reader can judge the shape of the bill before deciding to.

| Resource | Approximate driver | Dev default | Prod default |
|---|---|---|---|
| NAT gateway(s) | ~$0.045/hr + per-GB data processed, each | 1 shared | 1 per AZ (3) |
| MSK brokers | ~$0.0416-0.34/hr per broker (instance-type-dependent) + storage | 2x `kafka.t3.small` | 3x `kafka.m5.large` |
| RDS | Instance-hour + storage + (if Multi-AZ) a second standby instance | 1x `db.t4g.medium`, single-AZ | 1x `db.r6g.large`, Multi-AZ (2x cost) |
| ALB | ~$0.0225/hr + per-LCU-hour | 1 | 1 |
| ECS Fargate | vCPU-hour + GB-hour per running task, x13 services x desired count | ~15 tasks at 0.25-0.5 vCPU each | ~20+ tasks, some doubled for HA |
| ElastiCache | Instance-hour per node | 1x `cache.t4g.micro` | 2x `cache.r6g.large` |
| EMR Serverless | vCPU-second + GB-second, **only while a job is actually running** (auto-stops otherwise) | pay-per-use | pay-per-use, higher ceiling |
| S3 | Storage (tiered via lifecycle rules) + request count + data transfer out | usage-based | usage-based |
| VPC interface endpoints | ~$0.01/hr per endpoint per AZ + per-GB | 5 endpoints x 2 AZs | 5 endpoints x 3 AZs |
| Data transfer | Cross-AZ, NAT egress, internet egress | usage-based | usage-based |

The single largest avoidable line items for a demo/dev use are the NAT
gateway(s) (`single_nat_gateway = true` in dev) and MSK (the smallest
viable broker count/instance type is already the dev default).

## Variables

See each module's `variables.tf` for the full, documented list (every
variable has a `description`). Environment-level variables an operator
would actually set are in `environments/<env>/variables.tf` and
`terraform.tfvars.example` — notably `data_lake_bucket_suffix` (required,
for S3 global-uniqueness) and `certificate_arn` (required, must already
exist).

## Outputs

See `environments/<env>/outputs.tf`: ALB DNS name, ECR repository URLs,
RDS endpoint (no password), the RDS master-password secret ARN (for the
post-provision step below), MSK bootstrap brokers, the data-lake bucket
name, the EMR Serverless application ID, the ECS cluster name, and the
CloudWatch dashboard name. No secret *value* is ever output in plaintext.

## Post-provision manual step: the remaining 4 databases

RDS creates exactly one database (`var.database_name`, default
`omniflow_orders`) at instance-creation time. The other four
(`omniflow_inventory`, `omniflow_orchestrator`, `omniflow_gateway`,
`omniflow_failure_lab` — see `infra/docker/postgres/init-databases.sql` for
the local equivalent) are **not** created by this Terraform: the AWS
provider has no resource for creating an additional database inside an
existing RDS instance without a live `psql`/network connection, and this
task must not attempt that connection autonomously. After a real `apply`,
an operator would run (with real credentials, from a host with network
access to the RDS instance):

```bash
psql "postgresql://<master_username>@<rds_endpoint>/postgres" \
  -c "CREATE DATABASE omniflow_inventory;" \
  -c "CREATE DATABASE omniflow_orchestrator;" \
  -c "CREATE DATABASE omniflow_gateway;" \
  -c "CREATE DATABASE omniflow_failure_lab;"
```

(Password from the RDS master-password secret ARN in this environment's
outputs.)

## EMR Serverless: authored, never invoked

`modules/emr` provisions the persistent EMR Serverless *application* only.
Submitting an actual job run (the Spark equivalent of
`docker compose run spark-bronze`) is a separate, explicit operator/CI
action against the running application:

```bash
aws emr-serverless start-job-run \
  --application-id <from terraform output> \
  --execution-role-arn <from terraform output> \
  --job-driver '{"sparkSubmit": {"entryPoint": "s3://.../bronze.py", ...}}'
```

This Terraform never runs that command — matching every other
"authored, not invoked" boundary in this phase.

## Explicit assumptions and limitations

- **Never applied.** No `terraform plan` was run against a real account, no
  AWS credentials were used, no AWS API call of any kind was made while
  authoring this.
- **No remote backend configured** (local state only, per ADR 0007) —
  `backend.tf` documents the S3+DynamoDB setup a real deployment would use,
  commented out.
- **5 logical databases need a manual post-provision step** (above) — RDS
  creates only 1 at instance-creation time.
- **Distributed tracing has no cloud backend wired up.** Every service
  still calls `configure_tracing()` (OpenTelemetry, exporting to
  `OTEL_EXPORTER_OTLP_ENDPOINT`, default `http://otel-collector:4318`) —
  this Terraform does not set that env var to anything reachable in AWS
  (no Jaeger/ADOT collector is deployed here, matching the CloudWatch-only
  observability decision above), so trace export will fail silently
  (OTLP exporters retry/drop, they do not crash the service) rather than
  actually deliver anywhere. A real follow-up would add AWS Distro for
  OpenTelemetry (ADOT) or a self-hosted Jaeger-on-ECS service — out of this
  phase's scope.
- **ops-dashboard's nginx reverse proxy would need a config change to
  actually work in AWS.** Locally, `services/ops-dashboard/nginx.conf`
  resolves its upstream hostnames via Docker's embedded DNS at
  `127.0.0.11`. In this VPC, the equivalent is the Amazon-provided DNS
  resolver at `169.254.169.253` (constant across VPCs). This is an
  application-config change under `services/ops-dashboard/`, out of this
  phase's "author Terraform only" scope — named here rather than silently
  assumed to work.
- **data-platform's S3 client code expects explicit
  `MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD`.** The `lag-poller` ECS task's
  environment in this Terraform deliberately omits them (Fargate tasks
  should authenticate to S3 via their IAM task role, not static
  credentials) — `services/data-platform/app/s3.py` would need a small
  fallback (use `boto3`'s default credential chain when these env vars are
  unset) before `lag-poller` actually authenticates successfully in AWS.
  Named here, not silently assumed to work; not implemented, since it is
  an application-code change out of this phase's scope.
- **EMR Serverless custom-image compatibility not verified.** Actually
  running the existing `services/data-platform` bronze/silver/gold code
  under EMR Serverless would need building on EMR Serverless' required
  base image (or verifying the existing image's compatibility) — not
  attempted here, since it's an application/build change, not Terraform.
- **ElastiCache is modeled, not consumed.** No application code reads from
  Redis yet — `RISKS.md` #13 names this as the concrete next step for a
  horizontally-scaled gateway's rate limiter; this Terraform provisions the
  target infrastructure for that step, not the step itself.
- **ACM certificate and DNS are out of scope.** `certificate_arn` must
  already exist (issued/validated against a domain you own); no Route 53
  zone is created here.
- **Terraform state is sensitive.** `module.rds`'s `master_password` output
  and the composed per-service `DATABASE_URL` secret strings are all marked
  `sensitive` in Terraform's own output handling, but the *plaintext*
  values still exist in `terraform.tfstate` (this is normal, unavoidable
  Terraform behavior for any resource whose live value it manages) — a
  real deployment must treat the state file itself as a secret (encrypted
  remote backend, restricted IAM access to it), never commit it, and
  `.gitignore` already excludes `*.tfstate*` for exactly this reason.

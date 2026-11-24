# Staging stack, AWS Mumbai (ADR-0007). `terraform init && terraform plan -var-file=staging.tfvars`.
# Applying creates billable resources: run only with explicit approval.
terraform {
  required_version = ">= 1.9"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
  backend "s3" {} # bucket/key/region/dynamodb lock passed via -backend-config
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = "manima-one", Environment = "staging", ManagedBy = "terraform" }
  }
}

variable "region" {
  type    = string
  default = "ap-south-1"
}
variable "image_tag" { type = string }
variable "ecr_registry" { type = string }
variable "certificate_arn" { type = string }
# Pre-created Secrets Manager entries (full SQLAlchemy URLs incl. passwords for each DB role).
variable "secret_arns" {
  type = object({
    database_url           = string # manima_app (NOBYPASSRLS)
    platform_database_url  = string # manima_platform (BYPASSRLS)
    migration_database_url = string # manima (schema owner)
  })
}

locals {
  name = "manima-staging"
  api  = "${var.ecr_registry}/manima-api:${var.image_tag}"
  web  = "${var.ecr_registry}/manima-web:${var.image_tag}"
  common_env = {
    MANIMA_ENVIRONMENT   = "staging"
    MANIMA_REDIS_URL     = module.valkey.url
    MANIMA_COOKIE_SECURE = "true"
  }
  db_secrets = {
    MANIMA_DATABASE_URL          = var.secret_arns.database_url
    MANIMA_PLATFORM_DATABASE_URL = var.secret_arns.platform_database_url
  }
}

module "network" {
  source = "../../modules/network"
  name   = local.name
  azs    = ["ap-south-1a", "ap-south-1b"]
}

module "edge" {
  source            = "../../modules/edge"
  name              = local.name
  vpc_id            = module.network.vpc_id
  public_subnet_ids = module.network.public_subnet_ids
  certificate_arn   = var.certificate_arn
}

resource "aws_ecs_cluster" "this" {
  name = local.name
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

module "api" {
  source                     = "../../modules/ecs_service"
  name                       = "${local.name}-api"
  region                     = var.region
  cluster_arn                = aws_ecs_cluster.this.arn
  vpc_id                     = module.network.vpc_id
  subnet_ids                 = module.network.private_subnet_ids
  image                      = local.api
  container_port             = 8000
  desired_count              = 2
  environment                = local.common_env
  secrets                    = local.db_secrets
  ingress_security_group_ids = [module.edge.security_group_id]
  listener_arn               = module.edge.https_listener_arn
  path_patterns              = ["/api/*", "/healthz"]
  listener_priority          = 10
}

module "web" {
  source                     = "../../modules/ecs_service"
  name                       = "${local.name}-web"
  region                     = var.region
  cluster_arn                = aws_ecs_cluster.this.arn
  vpc_id                     = module.network.vpc_id
  subnet_ids                 = module.network.private_subnet_ids
  image                      = local.web
  container_port             = 3000
  desired_count              = 2
  health_check_path          = "/login"
  ingress_security_group_ids = [module.edge.security_group_id]
  listener_arn               = module.edge.https_listener_arn
  path_patterns              = ["/*"]
  listener_priority          = 100
}

module "worker" {
  source      = "../../modules/ecs_service"
  name        = "${local.name}-worker"
  region      = var.region
  cluster_arn = aws_ecs_cluster.this.arn
  vpc_id      = module.network.vpc_id
  subnet_ids  = module.network.private_subnet_ids
  image       = local.api
  command     = ["celery", "-A", "manima.workers.celery_app", "worker", "-Q", "critical,default", "-l", "info"]
  environment = local.common_env
  secrets     = local.db_secrets
}

module "beat" {
  source      = "../../modules/ecs_service"
  name        = "${local.name}-beat"
  region      = var.region
  cluster_arn = aws_ecs_cluster.this.arn
  vpc_id      = module.network.vpc_id
  subnet_ids  = module.network.private_subnet_ids
  image       = local.api
  cpu         = 256
  memory      = 512
  command     = ["celery", "-A", "manima.workers.celery_app", "beat", "-l", "info", "-s", "/tmp/beat"]
  environment = local.common_env
  secrets     = local.db_secrets
}

module "relay" {
  source      = "../../modules/ecs_service"
  name        = "${local.name}-relay"
  region      = var.region
  cluster_arn = aws_ecs_cluster.this.arn
  vpc_id      = module.network.vpc_id
  subnet_ids  = module.network.private_subnet_ids
  image       = local.api
  cpu         = 256
  memory      = 512
  command     = ["python", "-m", "manima.workers.relay"]
  environment = local.common_env
  secrets     = local.db_secrets
}

module "rds" {
  source     = "../../modules/rds_postgres"
  name       = local.name
  vpc_id     = module.network.vpc_id
  subnet_ids = module.network.private_subnet_ids
  allowed_security_group_ids = [
    module.api.security_group_id, module.worker.security_group_id,
    module.beat.security_group_id, module.relay.security_group_id,
  ]
}

module "valkey" {
  source     = "../../modules/valkey"
  name       = local.name
  vpc_id     = module.network.vpc_id
  subnet_ids = module.network.private_subnet_ids
  allowed_security_group_ids = [
    module.api.security_group_id, module.worker.security_group_id,
    module.beat.security_group_id, module.relay.security_group_id,
  ]
}

output "alb_dns_name" { value = module.edge.dns_name }
output "db_endpoint" { value = module.rds.endpoint }

# PostgreSQL on RDS: private, encrypted, Multi-AZ optional, deletion-protected.
# Application roles (manima_app NOBYPASSRLS, manima_platform BYPASSRLS) are created by the
# bootstrap job from infrastructure/docker/postgres-init.sh logic using the master secret.
variable "name" { type = string }
variable "vpc_id" { type = string }
variable "subnet_ids" { type = list(string) }
variable "allowed_security_group_ids" { type = list(string) }
variable "engine_version" {
  type    = string
  default = "16"
}
variable "instance_class" {
  type    = string
  default = "db.t4g.medium"
}
variable "allocated_storage" {
  type    = number
  default = 50
}
variable "multi_az" {
  type    = bool
  default = false
}
variable "backup_retention_days" {
  type    = number
  default = 14
}

resource "aws_db_subnet_group" "this" {
  name       = var.name
  subnet_ids = var.subnet_ids
}

resource "aws_security_group" "db" {
  name   = "${var.name}-db"
  vpc_id = var.vpc_id
  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = var.allowed_security_group_ids
  }
}

resource "aws_db_parameter_group" "this" {
  name   = var.name
  family = "postgres${var.engine_version}"
  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }
  parameter {
    name  = "timezone"
    value = "UTC"
  }
}

resource "aws_db_instance" "this" {
  identifier                          = var.name
  engine                              = "postgres"
  engine_version                      = var.engine_version
  instance_class                      = var.instance_class
  allocated_storage                   = var.allocated_storage
  max_allocated_storage               = var.allocated_storage * 4
  storage_type                        = "gp3"
  storage_encrypted                   = true
  db_name                             = "manima"
  username                            = "manima_master"
  manage_master_user_password         = true # stored in Secrets Manager, never in state as plaintext
  db_subnet_group_name                = aws_db_subnet_group.this.name
  vpc_security_group_ids              = [aws_security_group.db.id]
  parameter_group_name                = aws_db_parameter_group.this.name
  multi_az                            = var.multi_az
  backup_retention_period             = var.backup_retention_days
  deletion_protection                 = true
  skip_final_snapshot                 = false
  final_snapshot_identifier           = "${var.name}-final"
  performance_insights_enabled        = true
  iam_database_authentication_enabled = true
  auto_minor_version_upgrade          = true
  copy_tags_to_snapshot               = true
}

output "endpoint" { value = aws_db_instance.this.address }
output "master_secret_arn" { value = aws_db_instance.this.master_user_secret[0].secret_arn }
output "security_group_id" { value = aws_security_group.db.id }

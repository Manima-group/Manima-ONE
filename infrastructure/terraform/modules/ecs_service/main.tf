# One Fargate service (api, web, worker, relay, beat share this module). Secrets come from
# Secrets Manager / SSM by ARN; nothing sensitive is passed as plain environment.
variable "name" { type = string }
variable "cluster_arn" { type = string }
variable "vpc_id" { type = string }
variable "subnet_ids" { type = list(string) }
variable "image" { type = string }
variable "command" {
  type    = list(string)
  default = null
}
variable "cpu" {
  type    = number
  default = 512
}
variable "memory" {
  type    = number
  default = 1024
}
variable "desired_count" {
  type    = number
  default = 1
}
variable "container_port" {
  type    = number
  default = null
}
variable "environment" {
  type    = map(string)
  default = {}
}
variable "secrets" {
  type    = map(string) # env var name -> secret ARN
  default = {}
}
variable "ingress_security_group_ids" {
  type    = list(string)
  default = []
}
variable "listener_arn" {
  type    = string
  default = null
}
variable "path_patterns" {
  type    = list(string)
  default = ["/*"]
}
variable "listener_priority" {
  type    = number
  default = 100
}
variable "health_check_path" {
  type    = string
  default = "/healthz"
}
variable "region" { type = string }

locals { exposed = var.container_port != null }

resource "aws_cloudwatch_log_group" "this" {
  name              = "/manima/${var.name}"
  retention_in_days = 30
}

resource "aws_iam_role" "execution" {
  name = "${var.name}-exec"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "secrets" {
  count = length(var.secrets) > 0 ? 1 : 0
  role  = aws_iam_role.execution.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["secretsmanager:GetSecretValue", "ssm:GetParameters"], Resource = values(var.secrets) }]
  })
}

resource "aws_iam_role" "task" {
  name               = "${var.name}-task"
  assume_role_policy = aws_iam_role.execution.assume_role_policy
}

resource "aws_security_group" "svc" {
  name   = var.name
  vpc_id = var.vpc_id
  dynamic "ingress" {
    for_each = local.exposed ? [1] : []
    content {
      from_port       = var.container_port
      to_port         = var.container_port
      protocol        = "tcp"
      security_groups = var.ingress_security_group_ids
    }
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_ecs_task_definition" "this" {
  family                   = var.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn
  runtime_platform {
    cpu_architecture        = "ARM64"
    operating_system_family = "LINUX"
  }
  container_definitions = jsonencode([{
    name                   = var.name
    image                  = var.image
    command                = var.command
    essential              = true
    readonlyRootFilesystem = false
    portMappings           = local.exposed ? [{ containerPort = var.container_port }] : []
    environment            = [for k, v in var.environment : { name = k, value = v }]
    secrets                = [for k, v in var.secrets : { name = k, valueFrom = v }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.this.name
        awslogs-region        = var.region
        awslogs-stream-prefix = var.name
      }
    }
  }])
}

resource "aws_lb_target_group" "this" {
  count       = local.exposed ? 1 : 0
  name        = var.name
  port        = var.container_port
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = var.vpc_id
  health_check {
    path    = var.health_check_path
    matcher = "200-399"
  }
}

resource "aws_lb_listener_rule" "this" {
  count        = local.exposed && var.listener_arn != null ? 1 : 0
  listener_arn = var.listener_arn
  priority     = var.listener_priority
  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this[0].arn
  }
  condition {
    path_pattern { values = var.path_patterns }
  }
}

resource "aws_ecs_service" "this" {
  name            = var.name
  cluster         = var.cluster_arn
  task_definition = aws_ecs_task_definition.this.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"
  network_configuration {
    subnets         = var.subnet_ids
    security_groups = [aws_security_group.svc.id]
  }
  dynamic "load_balancer" {
    for_each = local.exposed ? [1] : []
    content {
      target_group_arn = aws_lb_target_group.this[0].arn
      container_name   = var.name
      container_port   = var.container_port
    }
  }
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
}

output "security_group_id" { value = aws_security_group.svc.id }

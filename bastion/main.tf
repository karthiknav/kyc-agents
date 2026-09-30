terraform {
  backend "s3" {
    bucket  = "kyc-agent-artifacts-360946915124-us-east-1"
    key     = "bastion/terraform.tfstate"
    region  = "us-east-1"
    encrypt = true
  }

  required_providers {
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

# Latest Windows Server AMI, resolved at apply time via the public SSM parameter.
data "aws_ssm_parameter" "windows_ami" {
  name = "/aws/service/ami-windows-latest/Windows_Server-2022-English-Full-Base"
}

# Sets the Administrator password directly via user_data instead of the usual
# key-pair + get-password-data flow, so no EC2 key pair is needed at all.
# Randomly generated (not a fixed/simple value) since this account is reached
# by anyone with ssm:StartSession on this instance - keeping it strong costs
# nothing and this is the only thing standing between that access and the box.
resource "random_password" "admin" {
  length      = 20
  special     = true
  min_upper   = 2
  min_lower   = 2
  min_numeric = 2
  min_special = 2
  # Windows local-account passwords reject some symbols; keep to a safe set.
  override_special = "!@#$%^&*()-_=+"
}

# No inbound rules at all: RDP reaches the instance through an SSM Session
# Manager port-forward tunnel, not a directly opened port. Avoids reproducing
# the "unrestricted admin port" pattern already remediated for this VPC
# (see ../NACL-COMPLIANCE.md) and needs no NACL changes since 3389 never
# crosses the subnet boundary.
resource "aws_security_group" "rdp_bastion" {
  name        = "${var.name}-sg"
  description = "Windows RDP bastion - no inbound; access via SSM port-forward"
  vpc_id      = var.vpc_id

  tags = {
    Name = var.name
  }
}

resource "aws_security_group_rule" "rdp_bastion_egress" {
  type              = "egress"
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.rdp_bastion.id
}

# Optional: only used if var.allowed_rdp_cidr is set, for direct RDP instead
# of/in addition to the SSM tunnel. Left unset by default.
resource "aws_security_group_rule" "rdp_bastion_direct_rdp" {
  count             = var.allowed_rdp_cidr == null ? 0 : 1
  type              = "ingress"
  from_port         = 3389
  to_port           = 3389
  protocol          = "tcp"
  cidr_blocks       = [var.allowed_rdp_cidr]
  security_group_id = aws_security_group.rdp_bastion.id
}

resource "aws_iam_role" "rdp_bastion_ssm" {
  name = "${var.name}-ssm-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "rdp_bastion_ssm" {
  role       = aws_iam_role.rdp_bastion_ssm.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "rdp_bastion" {
  name = "${var.name}-instance-profile"
  role = aws_iam_role.rdp_bastion_ssm.name
}

resource "aws_instance" "rdp_bastion" {
  ami                    = data.aws_ssm_parameter.windows_ami.value
  instance_type          = var.instance_type
  subnet_id              = var.subnet_id
  vpc_security_group_ids = [aws_security_group.rdp_bastion.id]
  iam_instance_profile   = aws_iam_instance_profile.rdp_bastion.name

  # Sets the local Administrator password on first boot; runs via EC2Launch.
  # No key pair needed since we're not relying on the encrypted
  # get-password-data flow.
  user_data = <<-EOF
    <script>
    net user Administrator "${random_password.admin.result}"
    </script>
  EOF

  # Private subnet, no public IP - reached only via SSM tunnel/VPN, never
  # exposed to the internet.
  associate_public_ip_address = false

  metadata_options {
    http_tokens = "required" # enforce IMDSv2
  }

  root_block_device {
    volume_size = var.root_volume_size_gb
    volume_type = "gp3"
    encrypted   = true
  }

  tags = {
    Name = var.name
  }
}

variable "name" {
  description = "Name prefix for resources"
  type        = string
  default     = "kyc-rdp-bastion"
}

variable "vpc_id" {
  description = "Existing VPC ID (same VPC as the KYC workloads/Langfuse)"
  type        = string
  default     = "vpc-047cc3057ce1bf76f"
}

variable "subnet_id" {
  description = "Private subnet ID to launch the bastion into (no public IP is assigned)"
  type        = string
  default     = "subnet-07ca4afcf672d8520"
}

variable "instance_type" {
  description = "EC2 instance type for the Windows bastion"
  type        = string
  default     = "t3.medium"
}

variable "key_pair_name" {
  description = "Name of an existing EC2 key pair, used only to decrypt the initial Windows Administrator password (create with 'aws ec2 create-key-pair' if you don't have one - do not commit the .pem)"
  type        = string
}

variable "root_volume_size_gb" {
  description = "Root EBS volume size in GB"
  type        = number
  default     = 50
}

variable "allowed_rdp_cidr" {
  description = "If set, opens 3389 inbound directly from this CIDR (e.g. 'YOUR.IP.ADDR.ESS/32') instead of relying solely on the SSM port-forward tunnel. Leave null unless you specifically need direct RDP."
  type        = string
  default     = null
}

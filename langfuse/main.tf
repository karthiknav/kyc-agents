provider "aws" {
  region = "us-east-1"
}

module "langfuse" {
  source = "./langfuse-terraform-aws"

  name   = "langfuse"
  domain = "langfuse.gen-ai-designs.com"

  # 👇 your existing VPC
  vpc_id             = "vpc-0471d506bfc76f3d9"
  private_subnet_ids = ["subnet-093a6535e084d1b87", "subnet-0bc3915284f4d7cae"]
  public_subnet_ids  = ["subnet-0047a37be8d0a9a6d", "subnet-0ff49bee49396da89"]

  private_route_table_ids = ["rtb-040d1056d5cab6969"]
}

provider "kubernetes" {
  host                   = module.langfuse.cluster_host
  cluster_ca_certificate = module.langfuse.cluster_ca_certificate
  token                  = module.langfuse.cluster_token

  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--cluster-name", module.langfuse.cluster_name]
  }
}

provider "helm" {
  kubernetes {
    host                   = module.langfuse.cluster_host
    cluster_ca_certificate = module.langfuse.cluster_ca_certificate
    token                  = module.langfuse.cluster_token

    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args        = ["eks", "get-token", "--cluster-name", module.langfuse.cluster_name]
    }
  }
}


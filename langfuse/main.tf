provider "aws" {
  region = "us-east-1"
}

module "langfuse" {
  source = "./langfuse-terraform-aws"

  name   = "langfuse"
  domain = "langfuse.genaidesigns.net"

  # 👇 your existing VPC
  vpc_id             = "vpc-003d95b5660ef0ca6"
  private_subnet_ids = ["subnet-03bfcbfcff49fbbf6", "subnet-0caf26118ad8e46b2"]
  public_subnet_ids  = ["subnet-06b5042bc39082a02", "subnet-0d17103d87fcbc8ab"]

  private_route_table_ids = ["rtb-0285ef08cf827becc"]
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


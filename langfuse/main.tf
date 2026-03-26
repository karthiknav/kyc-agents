provider "aws" {
  region = "us-east-1"
}

module "langfuse" {
  source = "./langfuse-terraform-aws"

  name   = "langfuse"
  domain = "langfuse.noonehasthisdomain.click"

  # 👇 your existing VPC
  vpc_id             = "vpc-0b5d62a8e372728e9"
  private_subnet_ids = ["subnet-026f9234ed6d23623", "subnet-0b8a7a17618511a6a"]
  public_subnet_ids  = ["subnet-009754e40f5ceabfe", "subnet-0f91f20160c798e26"]

  private_route_table_ids = ["rtb-0664d2f6c957b8376"]
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


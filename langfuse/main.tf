provider "aws" {
  region = "us-east-1"
}

module "langfuse" {
  source = "./langfuse-terraform-aws"

  name   = "langfuse"
  domain = "langfuse.noonehasthisdomain.click"

  # 👇 your existing VPC
  vpc_id             = "vpc-01b50e8d924139309"
  private_subnet_ids = ["subnet-066debb2ea159ed4b", "subnet-025e2f39448f95a45"]
  public_subnet_ids  = ["subnet-0b6d3c40a09a2d2c8", "subnet-0754a7a3e5ea079a0"]

  private_route_table_ids = ["rtb-02ac52a23fde86424"]
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


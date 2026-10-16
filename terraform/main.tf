terraform {
  required_version = ">= 1.5.0"
  required_providers {
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 3.3.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.12.0"
    }
  }
}

provider "kubernetes" {
  config_path = var.kubeconfig_path
}

provider "helm" {
  kubernetes {
    config_path = var.kubeconfig_path
  }
}

module "cluster" {
  source           = "./modules/cluster"
  tenant_namespace = var.tenant_namespace
}

module "platform_addons" {
  source            = "./modules/platform_addons"
  tenant_namespace  = module.cluster.tenant_namespace_name
  argocd_namespace  = var.argocd_namespace
  monitoring_ns     = var.monitoring_namespace
}

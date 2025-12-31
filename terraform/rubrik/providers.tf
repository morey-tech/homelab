terraform {
  required_providers {
    maas = {
      source  = "maas/maas"
      version = "~> 2.1"
    }
  }
}

provider "maas" {
  api_version              = "2.0"
  api_key                  = var.maas_api_key # TF_VAR_maas_api_key
  api_url                  = "http://192.168.3.109:5240/MAAS"
  tls_insecure_skip_verify = true
}
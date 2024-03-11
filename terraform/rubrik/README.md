# Terraform
## Rubrik
Populate the local `terraform.tfvars` file:
```
# terraform.tfvars
maas_api_key    = ""
maas_power_pass = ""
```
- http://192.168.3.109:5240/MAAS/r/account/prefs/api-keys

Deploy with Terraform:
```
terraform apply
```
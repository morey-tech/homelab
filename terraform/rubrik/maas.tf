resource "maas_fabric" "home_morey_tech" {
  name = "home-morey-tech"
}

resource "maas_vlan" "lan" {
  fabric = maas_fabric.home_morey_tech.id
  vid    = 1
  name   = "lan"
}

resource "maas_vlan" "lab" {
  fabric = maas_fabric.home_morey_tech.id
  vid    = 3
  # name   = "lab"
  name   = "untagged"
}

resource "maas_vlan" "bmc" {
  fabric = maas_fabric.home_morey_tech.id
  vid    = 6
  name   = "bmc"
}

resource "maas_vlan" "k8s_hosts" {
  fabric = maas_fabric.home_morey_tech.id
  vid    = 8
  name   = "k8s-hosts"
}

resource "maas_machine" "rubrik_c" {
  power_type = "ipmi"
  power_parameters = jsonencode({
    "cipher_suite_id" : "3",
    "k_g" : "",
    "mac_address" : "0C:C4:7A:5A:8A:30",
    "power_address" : "192.168.3.202",
    "power_boot_type" : "auto",
    "power_driver" : "LAN_2_0",
    "power_pass" : var.maas_power_pass,
    "power_user" : var.maas_power_user,
    "privilege_level" : "ADMIN"
  })
  pxe_mac_address = "0c:c4:7a:52:0f:8e"
}

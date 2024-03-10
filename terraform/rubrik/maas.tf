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

resource "maas_subnet" "lan" {
  cidr       = "192.168.1.0/24"
  fabric     = maas_fabric.home_morey_tech.id
  vlan       = maas_vlan.lan.vid
  name       = "lan"
  gateway_ip = "192.168.1.1"
  ip_ranges {
    type     = "reserved"
    start_ip = "192.168.1.100"
    end_ip   = "192.168.1.200"
    comment  = "pfSense DHCP"
  }
}

resource "maas_subnet" "lab" {
  cidr       = "192.168.3.0/24"
  fabric     = maas_fabric.home_morey_tech.id
  vlan       = maas_vlan.lab.vid
  name       = "lab"
  gateway_ip = "192.168.3.1"
  ip_ranges {
    type     = "reserved"
    start_ip = "192.168.3.1"
    end_ip   = "192.168.3.10"
    comment  = "static hardware"
  }
  ip_ranges {
    type     = "reserved"
    start_ip = "192.168.3.100"
    end_ip   = "192.168.3.199"
    comment  = "proxmox"
  }
  ip_ranges {
    type     = "reserved"
    start_ip = "192.168.3.200"
    end_ip   = "192.168.3.250"
    comment  = "lab bmc"
  }
}

resource "maas_subnet" "bmc" {
  cidr       = "192.168.6.0/24"
  fabric     = maas_fabric.home_morey_tech.id
  vlan       = maas_vlan.bmc.vid
  name       = "bmc"
  gateway_ip = "192.168.6.1"
}

resource "maas_subnet" "k8s_hosts" {
  cidr       = "192.168.8.0/24"
  fabric     = maas_fabric.home_morey_tech.id
  vlan       = maas_vlan.k8s_hosts.vid
  name       = "k8s-hosts"
  gateway_ip = "192.168.8.1"
  ip_ranges {
    type     = "dynamic"
    start_ip = "192.168.8.200"
    end_ip   = "192.168.8.250"
    comment  = "Dynamic"
  }
}

resource "maas_dns_domain" "lab_home_morey_tech" {
  name          = "lab.home.morey.tech"
  ttl           = 60
  authoritative = true
}

resource "maas_dns_domain" "maas_home_morey_tech" {
  name          = "maas.home.morey.tech"
  ttl           = 60
  authoritative = true
  is_default    = true
}

resource "maas_machine" "rubrik_c" {
  hostname = "rubrik-c"
  domain = maas_dns_domain.maas_home_morey_tech.name
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

resource "maas_network_interface_physical" "rubrik_c_eno1" {
  machine     = maas_machine.rubrik_c.id
  mac_address = "0c:c4:7a:52:0f:8e"
  name        = "eno1"
  vlan        = maas_vlan.lab.id
}

resource "maas_network_interface_physical" "rubrik_c_eno2" {
  machine     = maas_machine.rubrik_c.id
  mac_address = "0c:c4:7a:52:0f:8f"
  name        = "eno2"
  vlan        = maas_vlan.lab.id
}

resource "maas_network_interface_physical" "rubrik_c_ens1f0" {
  machine     = maas_machine.rubrik_c.id
  mac_address = "0c:c4:7a:58:47:14"
  name        = "ens1f0"
  vlan        = maas_vlan.lab.id
}

resource "maas_network_interface_physical" "rubrik_c_ens1f1" {
  machine     = maas_machine.rubrik_c.id
  mac_address = "0c:c4:7a:58:47:15"
  name        = "ens1f1"
  vlan        = 0
}

resource "maas_network_interface_link" "rubrik_c_eno1" {
  machine           = maas_machine.rubrik_c.id
  network_interface = maas_network_interface_physical.rubrik_c_eno1.id
  subnet            = maas_subnet.lab.id
  mode              = "STATIC"
  ip_address        = "192.168.3.18"
  default_gateway   = true
}
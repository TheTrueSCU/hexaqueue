# Query all Oracle Services Network services in the region for Service Gateway routing
data "oci_core_services" "all_services" {
  filter {
    name   = "name"
    values = [".*Oracle Services Network.*"]
    regex  = true
  }
}

locals {
  target_compartment = var.compartment_ocid != "" ? var.compartment_ocid : var.tenancy_ocid
}

# Service Gateway allowing private workers to access OCI Object Storage and Vault directly
resource "oci_core_service_gateway" "hq_service_gateway" {
  compartment_id = local.target_compartment
  vcn_id         = var.vcn_ocid
  display_name   = "hq-service-gateway"

  services {
    service_id = data.oci_core_services.all_services.services[0].id
  }
}

# NAT Gateway providing private workers outbound access to PyPI, GitHub, and OS updates
resource "oci_core_nat_gateway" "hq_nat_gateway" {
  compartment_id = local.target_compartment
  vcn_id         = var.vcn_ocid
  display_name   = "hq-nat-gateway"
}

# Route table for private worker subnet routing OSN to Service Gateway and 0.0.0.0/0 to NAT Gateway
resource "oci_core_route_table" "hq_worker_route_table" {
  compartment_id = local.target_compartment
  vcn_id         = var.vcn_ocid
  display_name   = "hq-worker-private-route-table"

  route_rules {
    destination       = data.oci_core_services.all_services.services[0].cidr_block
    destination_type  = "SERVICE_CIDR_BLOCK"
    network_entity_id = oci_core_service_gateway.hq_service_gateway.id
    description       = "Oracle Services Network via Service Gateway"
  }

  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_nat_gateway.hq_nat_gateway.id
    description       = "Default outbound internet egress via NAT Gateway"
  }
}

# Private Worker Subnet (prohibiting public IP assignment)
resource "oci_core_subnet" "hq_worker_subnet" {
  compartment_id             = local.target_compartment
  vcn_id                     = var.vcn_ocid
  cidr_block                 = var.worker_subnet_cidr
  display_name               = "hq-worker-private-subnet"
  dns_label                  = "hqworker"
  prohibit_public_ip_on_vnic = true
  route_table_id             = oci_core_route_table.hq_worker_route_table.id
}

# Network Security Group for the Controller Node
resource "oci_core_network_security_group" "controller_nsg" {
  compartment_id = local.target_compartment
  vcn_id         = var.vcn_ocid
  display_name   = "hq-controller-nsg"
}

# Ingress rule: allow worker NSG to connect to Controller internal worker port (8001)
resource "oci_core_network_security_group_security_rule" "controller_ingress_worker" {
  network_security_group_id = oci_core_network_security_group.controller_nsg.id
  direction                 = "INGRESS"
  protocol                  = "6" # TCP
  source                    = oci_core_network_security_group.worker_nsg.id
  source_type               = "NETWORK_SECURITY_GROUP"
  description               = "Allow worker pool instances to reach controller worker API on port 8001"

  tcp_options {
    destination_port_range {
      min = 8001
      max = 8001
    }
  }
}

# Network Security Group for Worker Pool Nodes
resource "oci_core_network_security_group" "worker_nsg" {
  compartment_id = local.target_compartment
  vcn_id         = var.vcn_ocid
  display_name   = "hq-worker-nsg"
}

# Egress rule: allow workers to reach controller internal port (8001)
resource "oci_core_network_security_group_security_rule" "worker_egress_controller" {
  network_security_group_id = oci_core_network_security_group.worker_nsg.id
  direction                 = "EGRESS"
  protocol                  = "6" # TCP
  destination               = oci_core_network_security_group.controller_nsg.id
  destination_type          = "NETWORK_SECURITY_GROUP"
  description               = "Allow worker instances to contact controller worker API"

  tcp_options {
    destination_port_range {
      min = 8001
      max = 8001
    }
  }
}

# Egress rule: allow workers outbound HTTPS (443) to Service Gateway and NAT Gateway
resource "oci_core_network_security_group_security_rule" "worker_egress_https" {
  network_security_group_id = oci_core_network_security_group.worker_nsg.id
  direction                 = "EGRESS"
  protocol                  = "6" # TCP
  destination               = "0.0.0.0/0"
  destination_type          = "CIDR_BLOCK"
  description               = "Allow worker outbound HTTPS for package downloads and Object Storage"

  tcp_options {
    destination_port_range {
      min = 443
      max = 443
    }
  }
}

# Egress rule: allow workers outbound DNS (UDP 53)
resource "oci_core_network_security_group_security_rule" "worker_egress_dns" {
  network_security_group_id = oci_core_network_security_group.worker_nsg.id
  direction                 = "EGRESS"
  protocol                  = "17" # UDP
  destination               = "0.0.0.0/0"
  destination_type          = "CIDR_BLOCK"
  description               = "Allow worker DNS resolution"

  udp_options {
    destination_port_range {
      min = 53
      max = 53
    }
  }
}

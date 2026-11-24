# Instance Configuration for A1.Flex burst workers
resource "oci_core_instance_configuration" "worker_config" {
  compartment_id = local.target_compartment
  display_name   = "hq-worker-config-a1"

  instance_details {
    instance_type = "compute"

    launch_details {
      compartment_id = local.target_compartment
      display_name   = "hq-worker-burst"
      shape          = var.worker_shape

      shape_config {
        ocpus         = var.worker_ocpus
        memory_in_gbs = var.worker_memory_gbs
      }

      source_details {
        source_type             = "image"
        image_id                = var.worker_image_ocid
        boot_volume_size_in_gbs = 50
      }

      create_vnic_details {
        subnet_id        = oci_core_subnet.hq_worker_subnet.id
        display_name     = "hq-worker-vnic"
        assign_public_ip = false
        nsg_ids          = [oci_core_network_security_group.worker_nsg.id]
      }

      metadata = merge(
        {
          user_data = base64encode(templatefile("${path.module}/templates/worker_bootstrap.sh", {
            controller_ip    = var.controller_private_ip
            controller_port  = var.controller_port
            worker_ocpus     = var.worker_ocpus
            worker_memory_mb = var.worker_memory_gbs * 1024
          }))
        },
        var.ssh_public_key != "" ? { ssh_authorized_keys = var.ssh_public_key } : {}
      )
    }
  }

  lifecycle {
    create_before_destroy = true
  }
}

# Scale-to-zero Instance Pool
resource "oci_core_instance_pool" "worker_pool" {
  compartment_id            = local.target_compartment
  instance_configuration_id = oci_core_instance_configuration.worker_config.id
  display_name              = "hq-worker-pool-a1"
  size                      = var.pool_size

  dynamic "placement_configurations" {
    for_each = var.availability_domains
    content {
      availability_domain = placement_configurations.value
      primary_subnet_id   = oci_core_subnet.hq_worker_subnet.id
    }
  }

  lifecycle {
    ignore_changes = [size]
  }
}

# Instance Configuration for Ampere A4.Flex burst workers
resource "oci_core_instance_configuration" "worker_config_a4" {
  compartment_id = local.target_compartment
  display_name   = "hq-worker-config-a4"

  instance_details {
    instance_type = "compute"

    launch_details {
      compartment_id = local.target_compartment
      display_name   = "hq-worker-a4"
      shape          = var.worker_a4_shape

      shape_config {
        ocpus         = var.worker_a4_ocpus
        memory_in_gbs = var.worker_a4_memory_gbs
      }

      source_details {
        source_type             = "image"
        image_id                = var.worker_image_ocid
        boot_volume_size_in_gbs = 50
      }

      create_vnic_details {
        subnet_id        = oci_core_subnet.hq_worker_subnet.id
        display_name     = "hq-worker-a4-vnic"
        assign_public_ip = false
        nsg_ids          = [oci_core_network_security_group.worker_nsg.id]
      }

      metadata = merge(
        {
          user_data = base64encode(templatefile("${path.module}/templates/worker_bootstrap.sh", {
            controller_ip    = var.controller_private_ip
            controller_port  = var.controller_port
            worker_ocpus     = var.worker_a4_ocpus
            worker_memory_mb = var.worker_a4_memory_gbs * 1024
          }))
        },
        var.ssh_public_key != "" ? { ssh_authorized_keys = var.ssh_public_key } : {}
      )
    }
  }

  lifecycle {
    create_before_destroy = true
  }
}

# Scale-to-zero Instance Pool (Ampere A4.Flex)
resource "oci_core_instance_pool" "worker_pool_a4" {
  compartment_id            = local.target_compartment
  instance_configuration_id = oci_core_instance_configuration.worker_config_a4.id
  display_name              = "hq-worker-pool-a4"
  size                      = var.pool_size

  dynamic "placement_configurations" {
    for_each = var.worker_a4_availability_domains
    content {
      availability_domain = placement_configurations.value
      primary_subnet_id   = oci_core_subnet.hq_worker_subnet.id
    }
  }

  lifecycle {
    ignore_changes = [size]
  }
}

# Instance Configuration for AMD E5.Flex burst workers (x86_64 multi-AD fallback)
resource "oci_core_instance_configuration" "worker_config_e5" {
  compartment_id = local.target_compartment
  display_name   = "hq-worker-config-e5"

  instance_details {
    instance_type = "compute"

    launch_details {
      compartment_id = local.target_compartment
      display_name   = "hq-worker-e5"
      shape          = var.worker_e5_shape

      shape_config {
        ocpus         = var.worker_e5_ocpus
        memory_in_gbs = var.worker_e5_memory_gbs
      }

      source_details {
        source_type             = "image"
        image_id                = var.worker_image_x86_ocid
        boot_volume_size_in_gbs = 50
      }

      create_vnic_details {
        subnet_id        = oci_core_subnet.hq_worker_subnet.id
        display_name     = "hq-worker-e5-vnic"
        assign_public_ip = false
        nsg_ids          = [oci_core_network_security_group.worker_nsg.id]
      }

      metadata = merge(
        {
          user_data = base64encode(templatefile("${path.module}/templates/worker_bootstrap.sh", {
            controller_ip    = var.controller_private_ip
            controller_port  = var.controller_port
            worker_ocpus     = var.worker_e5_ocpus
            worker_memory_mb = var.worker_e5_memory_gbs * 1024
          }))
        },
        var.ssh_public_key != "" ? { ssh_authorized_keys = var.ssh_public_key } : {}
      )
    }
  }

  lifecycle {
    create_before_destroy = true
  }
}

# Scale-to-zero Instance Pool (AMD E5.Flex across PHX-AD-1/2/3)
resource "oci_core_instance_pool" "worker_pool_e5" {
  compartment_id            = local.target_compartment
  instance_configuration_id = oci_core_instance_configuration.worker_config_e5.id
  display_name              = "hq-worker-pool-e5"
  size                      = var.pool_size

  dynamic "placement_configurations" {
    for_each = var.worker_e5_availability_domains
    content {
      availability_domain = placement_configurations.value
      primary_subnet_id   = oci_core_subnet.hq_worker_subnet.id
    }
  }

  lifecycle {
    ignore_changes = [size]
  }
}

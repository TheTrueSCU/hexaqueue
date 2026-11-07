# Instance Configuration for A1.Flex burst workers
resource "oci_core_instance_configuration" "worker_config" {
  compartment_id = local.target_compartment
  display_name   = "hq-worker-config-a1"

  instance_details {
    instance_type = "compute"

    launch_details {
      compartment_id = local.target_compartment
      display_name   = "hq-worker-burst"
      shape          = "VM.Standard.A1.Flex"

      shape_config {
        ocpus         = var.worker_ocpus
        memory_in_gbs = var.worker_memory_gbs
      }

      source_details {
        source_type             = "image"
        image_id                = var.worker_image_ocid
        boot_volume_size_in_gbs = 47
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
            controller_ip   = var.controller_private_ip
            controller_port = 8001
            worker_ocpus    = var.worker_ocpus
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

  placement_configurations {
    availability_domain = var.availability_domain
    primary_subnet_id   = oci_core_subnet.hq_worker_subnet.id
  }
}

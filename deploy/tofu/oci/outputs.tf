output "collateral_bucket_name" {
  description = "Name of the collateral and coverage Object Storage bucket"
  value       = oci_objectstorage_bucket.collateral.name
}

output "worker_private_subnet_id" {
  description = "OCID of the private worker subnet"
  value       = oci_core_subnet.hq_worker_subnet.id
}

output "worker_instance_pool_id" {
  description = "OCID of the scale-to-zero worker instance pool"
  value       = oci_core_instance_pool.worker_pool.id
}

output "worker_instance_pool_a4_id" {
  description = "OCID of the Ampere A4 scale-to-zero worker instance pool"
  value       = oci_core_instance_pool.worker_pool_a4.id
}

output "worker_instance_pool_e5_id" {
  description = "OCID of the AMD E5.Flex scale-to-zero worker instance pool"
  value       = oci_core_instance_pool.worker_pool_e5.id
}

output "worker_instance_pool_priority_ids" {
  description = "Comma-separated priority list of worker pool OCIDs (A1 -> A4 -> E5)"
  value       = join(",", [oci_core_instance_pool.worker_pool.id, oci_core_instance_pool.worker_pool_a4.id, oci_core_instance_pool.worker_pool_e5.id])
}

output "worker_nsg_id" {
  description = "OCID of the worker Network Security Group"
  value       = oci_core_network_security_group.worker_nsg.id
}

output "controller_nsg_id" {
  description = "OCID of the controller Network Security Group"
  value       = oci_core_network_security_group.controller_nsg.id
}

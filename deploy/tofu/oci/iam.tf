# Dynamic group for the always-on controller node
resource "oci_identity_dynamic_group" "controller_dg" {
  compartment_id = var.tenancy_ocid
  name           = "hq-controller-dg"
  description    = "Hexaqueue Controller instance dynamic group"
  matching_rule  = "instance.compartment.id = '${local.target_compartment}'"
}

# Policy allowing the controller instance principal to manage instance pools and issue PARs on the bucket
resource "oci_identity_policy" "controller_policy" {
  compartment_id = var.tenancy_ocid
  name           = "hq-controller-policy"
  description    = "Policy granting Hexaqueue Controller access to manage worker pools and collateral storage"
  statements = [
    "Allow dynamic-group hq-controller-dg to manage instance-pools in tenancy",
    "Allow dynamic-group hq-controller-dg to manage instance-configurations in tenancy",
    "Allow dynamic-group hq-controller-dg to manage instance-family in tenancy",
    "Allow dynamic-group hq-controller-dg to use virtual-network-family in tenancy",
    "Allow dynamic-group hq-controller-dg to use subnets in tenancy",
    "Allow dynamic-group hq-controller-dg to use vnics in tenancy",
    "Allow dynamic-group hq-controller-dg to manage object-family in tenancy"
  ]
}

# Policy granting the regional Object Storage service principal permission to evaluate lifecycle deletion rules
resource "oci_identity_policy" "objectstorage_lifecycle_policy" {
  compartment_id = var.tenancy_ocid
  name           = "hq-objectstorage-lifecycle-policy"
  description    = "Policy allowing OCI Object Storage service principal to execute automated lifecycle expiration"
  statements = [
    "Allow service objectstorage-${var.region} to manage object-family in tenancy"
  ]
}

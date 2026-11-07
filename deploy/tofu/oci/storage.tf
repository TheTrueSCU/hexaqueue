# Collateral and coverage storage bucket
resource "oci_objectstorage_bucket" "collateral" {
  compartment_id = local.target_compartment
  namespace      = var.object_storage_namespace
  name           = "hexaqueue-collateral"
  access_type    = "NoPublicAccess"
  auto_tiering   = "Disabled"
  storage_tier   = "Standard"
}

# Lifecycle policy: purge ephemeral test artifacts and collateral after 24 hours
resource "oci_objectstorage_object_lifecycle_policy" "collateral_lifecycle" {
  namespace  = var.object_storage_namespace
  bucket     = oci_objectstorage_bucket.collateral.name
  depends_on = [oci_identity_policy.objectstorage_lifecycle_policy]

  rules {
    name        = "purge-ephemeral-collateral-24h"
    action      = "DELETE"
    is_enabled  = true
    time_amount = 1
    time_unit   = "DAYS"
    target      = "objects"
  }
}

variable "tenancy_ocid" {
  description = "OCID of the OCI tenancy"
  type        = string
  default     = "ocid1.tenancy.oc1..aaaaaaaauojnvllfdpm7epqa3akbmflol7vz3yn5vgfibvaf76ak36tw3tua"
}

variable "region" {
  description = "OCI region identifier"
  type        = string
  default     = "us-phoenix-1"
}

variable "compartment_ocid" {
  description = "OCID of the compartment (defaults to tenancy root compartment if empty)"
  type        = string
  default     = ""
}

variable "object_storage_namespace" {
  description = "Namespace for OCI Object Storage"
  type        = string
  default     = "ax8nkvebgihr"
}

variable "vcn_ocid" {
  description = "OCID of the existing VCN"
  type        = string
  default     = "ocid1.vcn.oc1.phx.amaaaaaafqa2klyanleslac7fnq5gwmugoljxx4snd477c344bbgyxcmi3oa"
}

variable "controller_private_ip" {
  description = "Private IP address of the primary controller node"
  type        = string
  default     = "10.0.1.101"
}

variable "controller_port" {
  description = "Internal controller worker-pool API port"
  type        = number
  default     = 8001
}

variable "worker_subnet_cidr" {
  description = "CIDR block for the private worker subnet"
  type        = string
  default     = "10.0.2.0/24"
}

variable "worker_shape" {
  description = "Compute shape for burst worker instances (e.g. VM.Standard.A1.Flex or VM.Standard.A4.Flex)"
  type        = string
  default     = "VM.Standard.A1.Flex"
}

variable "worker_ocpus" {
  description = "OCPU count for burst Flex worker instances"
  type        = number
  default     = 2
}

variable "worker_memory_gbs" {
  description = "Memory in GB for burst Flex worker instances"
  type        = number
  default     = 12
}

variable "pool_size" {
  description = "Initial instance pool size (0 for scale-to-zero)"
  type        = number
  default     = 0
}

variable "worker_image_ocid" {
  description = "Canonical Ubuntu 24.04 aarch64 image OCID"
  type        = string
  default     = "ocid1.image.oc1.phx.aaaaaaaavvjouzivkqqwhwkrsb25lmqtibshn63gpy7dvvw4p5mk4c22kn3a"
}

variable "availability_domains" {
  description = "Availability domains for multi-AD burst worker placement"
  type        = list(string)
  default     = ["uPhp:PHX-AD-1", "uPhp:PHX-AD-2", "uPhp:PHX-AD-3"]
}

variable "ssh_public_key" {
  description = "SSH public key for worker debugging access if needed"
  type        = string
  default     = ""
}

variable "worker_a4_shape" {
  description = "Compute shape for Ampere A4 burst worker instances"
  type        = string
  default     = "VM.Standard.A4.Flex"
}

variable "worker_a4_ocpus" {
  description = "OCPU count for Ampere A4 burst worker instances"
  type        = number
  default     = 2
}

variable "worker_a4_memory_gbs" {
  description = "Memory in GB for Ampere A4 burst worker instances"
  type        = number
  default     = 12
}

variable "worker_a4_availability_domains" {
  description = "Availability domains for Ampere A4 burst worker placement"
  type        = list(string)
  default     = ["uPhp:PHX-AD-3"]
}

variable "worker_e5_shape" {
  description = "Compute shape for AMD E5.Flex burst worker instances"
  type        = string
  default     = "VM.Standard.E5.Flex"
}

variable "worker_e5_ocpus" {
  description = "OCPU count for AMD E5.Flex burst worker instances"
  type        = number
  default     = 4
}

variable "worker_e5_memory_gbs" {
  description = "Memory in GB for AMD E5.Flex burst worker instances"
  type        = number
  default     = 16
}

variable "worker_image_x86_ocid" {
  description = "Canonical Ubuntu 24.04 x86_64 image OCID for E5.Flex burst workers"
  type        = string
  default     = "ocid1.image.oc1.phx.aaaaaaaac4fywhiqjeemrjzi5sjyv6uuvcblywa5w3jefaym7bum52ugfzxq"
}

variable "worker_e5_availability_domains" {
  description = "Availability domains for AMD E5.Flex burst worker placement"
  type        = list(string)
  default     = ["uPhp:PHX-AD-1", "uPhp:PHX-AD-2", "uPhp:PHX-AD-3"]
}

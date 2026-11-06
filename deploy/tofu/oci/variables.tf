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

variable "public_subnet_ocid" {
  description = "OCID of the existing public subnet housing the controller"
  type        = string
  default     = "ocid1.subnet.oc1.phx.aaaaaaaazewllkw72a3ho36oyg5xmrtnr4kkxb3rdlgnvo6jz7vakqzf3bjq"
}

variable "controller_private_ip" {
  description = "Private IP address of the primary controller node"
  type        = string
  default     = "10.0.1.101"
}

variable "worker_subnet_cidr" {
  description = "CIDR block for the private worker subnet"
  type        = string
  default     = "10.0.2.0/24"
}

variable "worker_ocpus" {
  description = "OCPU count for burst A1.Flex worker instances"
  type        = number
  default     = 2
}

variable "worker_memory_gbs" {
  description = "Memory in GB for burst A1.Flex worker instances"
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

variable "availability_domain" {
  description = "Availability domain for instance placement"
  type        = string
  default     = "uPhp:PHX-AD-1"
}

variable "ssh_public_key" {
  description = "SSH public key for worker debugging access if needed"
  type        = string
  default     = ""
}

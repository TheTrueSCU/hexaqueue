# Hexaqueue OpenTofu Cloud Infrastructure

Declarative infrastructure-as-code (IaC) configurations for deploying Hexaqueue cluster coordinators, scale-to-zero instance pools, and content-addressable storage (CAS) collateral across cloud service providers.

## Topology

```text
deploy/tofu/
├── README.md
├── oci/     # Oracle Cloud Infrastructure (OCI) Always-Free / PAYG Elastic Stack (ADR-008)
└── gcp/     # Google Cloud Platform (GCP) Free Tier e2-micro Worker Stack (Phase 5)
```

## Providers

### Oracle Cloud Infrastructure (`oci/`)
Implements [ADR-008](file:///home/rjdw/Projects/hexaqueue/docs/decisions.md#L187-L230):
- **VCN & Subnets**: Private worker subnet (`10.0.2.0/24`) with strict `prohibit_public_ip_on_vnic = true`.
- **Gateways**: Service Gateway routing directly to Oracle Services Network (`all-phx-services-in-oracle-services-network`) and NAT Gateway for outbound package synchronization without public IPs.
- **Security**: Network Security Groups (`controller-nsg` and `worker-nsg`) confining worker-to-controller communication strictly to internal port 8001.
- **Storage**: `hexaqueue-collateral` Object Storage bucket with an automated 24-hour lifecycle deletion rule for ephemeral CAS bundles and test coverage artifacts.
- **Compute**: A1.Flex Arm Ampere instance configuration with scale-to-zero instance pool placement.

To initialize and validate the OCI stack:
```bash
cd deploy/tofu/oci
mise exec -- tofu init
mise exec -- tofu plan
```

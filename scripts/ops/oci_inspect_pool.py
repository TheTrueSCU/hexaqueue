"""OCI Instance Pool Inspection Utility.

Queries OCI Compute Management and Virtual Network APIs using Instance Principals
or local configuration to display current pool scaling status, instance states,
and private IP addresses.
"""

from __future__ import annotations

import os
import sys

DEFAULT_POOL_ID = "ocid1.instancepool.oc1.phx.aaaaaaaanrsntnef3gyouosagtedgyjj25h6oyr2cmuufzjsw7h3xaiapi5q"


def inspect_pool(pool_id: str | None = None) -> int:
    """Inspect and display OCI instance pool details and instance states.

    Args:
        pool_id: Optional OCI instance pool OCID. Defaults to env HEXAQUEUE_OCI_INSTANCE_POOL_ID.

    Returns:
        Exit code: 0 on success, non-zero on failure.
    """
    target_pool_id = (
        pool_id or os.environ.get("HEXAQUEUE_OCI_INSTANCE_POOL_ID") or DEFAULT_POOL_ID
    )

    try:
        import oci
    except ImportError:
        sys.stderr.write(
            "Error: 'oci' Python SDK is not installed. Run via 'uv run --with oci scripts/ops/oci_inspect_pool.py'\n"
        )
        return 1

    try:
        # Prefer Instance Principals (when running inside OCI compute), fallback to default config file
        try:
            signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
            config: dict[str, str] = {}
        except Exception:
            config = oci.config.from_file()
            signer = oci.signer.Signer(
                tenancy=config["tenancy"],
                user=config["user"],
                fingerprint=config["fingerprint"],
                private_key_file_location=config.get("key_file"),
            )

        mgmt_client = oci.core.ComputeManagementClient(config=config, signer=signer)
        net_client = oci.core.VirtualNetworkClient(config=config, signer=signer)
        compute_client = oci.core.ComputeClient(config=config, signer=signer)

        pool = mgmt_client.get_instance_pool(target_pool_id).data
        print(f"Instance Pool: {pool.display_name} ({pool.id})")
        print(f"Status:        {pool.lifecycle_state}")
        print(f"Target Size:   {pool.size}")
        print("-" * 75)

        instances = mgmt_client.list_instance_pool_instances(
            compartment_id=pool.compartment_id,
            instance_pool_id=target_pool_id,
        ).data

        header = f"{'Instance Name':<30} {'State':<12} {'Private IP':<16} {'OCID Suffix':<15}"
        print(header)
        print("=" * len(header))

        for inst in instances:
            private_ip = "pending"
            try:
                vnics = compute_client.list_vnic_attachments(
                    compartment_id=pool.compartment_id,
                    instance_id=inst.id,
                ).data
                if vnics:
                    vnic_data = net_client.get_vnic(vnics[0].vnic_id).data
                    private_ip = vnic_data.private_ip or "pending"
            except Exception:
                pass

            display_name = getattr(inst, "display_name", inst.id[-20:])
            ocid_suffix = f"...{inst.id[-12:]}"
            print(
                f"{display_name:<30} {inst.state:<12} {private_ip:<16} {ocid_suffix:<15}"
            )

        return 0

    except Exception as exc:
        sys.stderr.write(f"Error querying OCI instance pool: {exc}\n")
        return 2


if __name__ == "__main__":
    cli_pool_id = sys.argv[1] if len(sys.argv) > 1 else None
    sys.exit(inspect_pool(cli_pool_id))

"""Architecture and topology diagram generator for Hexaqueue documentation.

Notes/Architectural Intent:
    Uses the diagrams Python module to programmatically render vector and bitmap
    architectural topology diagrams illustrating Hexaqueue server roles, interface
    mix-and-match configurations, and distributed enterprise deployment patterns.
"""

import logging
from pathlib import Path

from diagrams import Cluster, Diagram, Edge
from diagrams.generic.compute import Rack
from diagrams.generic.os import LinuxGeneral
from diagrams.generic.storage import Storage
from diagrams.onprem.ci import GithubActions, GitlabCI
from diagrams.onprem.client import Client, User, Users
from diagrams.onprem.compute import Server
from diagrams.onprem.database import Postgresql
from diagrams.onprem.monitoring import Grafana, Prometheus
from diagrams.programming.framework import FastAPI
from diagrams.programming.language import Python, Rust
from hexaqual.adapters.workspace import get_repo_root

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

OUTPUT_DIR = get_repo_root(Path(__file__)) / "docs" / "assets" / "topologies"


def generate_single_node_diagram() -> None:
    """Generate architecture diagram for monolithic / all-in-one controller."""
    out_file = str(OUTPUT_DIR / "single_node")
    graph_attr = {
        "fontsize": "14",
        "bgcolor": "transparent",
        "pad": "0.5",
    }
    with Diagram(
        "Single-Node All-in-One Controller (role=all)",
        show=False,
        filename=out_file,
        outformat="png",
        graph_attr=graph_attr,
        direction="LR",
    ):
        with Cluster("Inbound Traffic"):
            cli = User("CLI / SDK User")
            webhooks = GithubActions("CI/CD Webhooks")
            agent = Client("AI Coding Assistant\n(MCP SSE)")

        with Cluster("Hexaqueue Node (Port 8000)"):
            server = Server("Hexaqueue Controller\n(Granian / Uvicorn)")
            with Cluster("Enabled Interfaces (9/9)"):
                ifaces = FastAPI(
                    "Runs, Jobs, Nodes, Logs,\nCluster, Collateral, Budget,\nWebhooks, FastMCP"
                )

        with Cluster("Cluster State & Storage"):
            db = Postgresql("PostgreSQL /\nSQLite")
            cas = Storage("CAS Artifacts\n(S3/GCS/FS)")

        with Cluster("Compute Fleet"):
            workers = [
                Rack("GPU Worker Pool"),
                LinuxGeneral("CPU Worker Pool"),
            ]

        cli >> Edge(label="REST /v1/runs") >> server
        webhooks >> Edge(label="HMAC Webhooks") >> server
        agent >> Edge(label="SSE /mcp/sse") >> server
        server - ifaces

        ifaces >> Edge(label="State & Ledger") >> db
        ifaces >> Edge(label="Artifact Staging") >> cas
        ifaces >> Edge(label="Task Leasing & Logs") >> workers


def generate_gateway_diagram() -> None:
    """Generate architecture diagram for Public Ingress Gateway node."""
    out_file = str(OUTPUT_DIR / "gateway_node")
    graph_attr = {
        "fontsize": "14",
        "bgcolor": "transparent",
        "pad": "0.5",
    }
    with Diagram(
        "Public Ingress Gateway Node (role=gateway)",
        show=False,
        filename=out_file,
        outformat="png",
        graph_attr=graph_attr,
        direction="LR",
    ):
        with Cluster("Public Ingress (Internet / DMZ)"):
            ci_gh = GithubActions("GitHub Inbound")
            ci_gl = GitlabCI("GitLab Inbound")
            devs = Users("Developers (CLI)")

        with Cluster("Public Gateway Node (Port 8000)"):
            gw = Server("Gateway Controller\n(Granian Rust ASGI)")
            with Cluster("Mounted Interfaces"):
                gw_ifaces = FastAPI(
                    "Active:\n/v1/runs, /v1/jobs\n/v1/collateral, /v1/webhooks\n\nBlocked:\nNodes, Logs, Budget, MCP"
                )

        with Cluster("Internal Network / Shared Bus"):
            db = Postgresql("Shared DB / Outbox")
            cas = Storage("CAS Object Store")
            internal = Server("Private Scheduler &\nWorker Coordinator")

        ci_gh >> Edge(label="Signature-Verified") >> gw
        ci_gl >> Edge(label="HMAC Webhook") >> gw
        devs >> Edge(label="DAG Submissions") >> gw
        gw - gw_ifaces
        gw_ifaces >> Edge(label="Persist Runs") >> db
        gw_ifaces >> Edge(label="Stage Artifacts") >> cas
        db >> Edge(label="Internal Dispatch") >> internal


def generate_worker_api_diagram() -> None:
    """Generate architecture diagram for Dedicated Worker Coordinator node."""
    out_file = str(OUTPUT_DIR / "worker_api_node")
    graph_attr = {
        "fontsize": "14",
        "bgcolor": "transparent",
        "pad": "0.5",
    }
    with Diagram(
        "Worker Coordinator Node (role=worker-api)",
        show=False,
        filename=out_file,
        outformat="png",
        graph_attr=graph_attr,
        direction="LR",
    ):
        with Cluster("HPC Compute Subnet (Private VPC)"):
            gpu_nodes = [Rack("NVIDIA H100 Node 01"), Rack("NVIDIA H100 Node 02")]
            cpu_nodes = [
                LinuxGeneral("High-CPU Node 01"),
                LinuxGeneral("High-CPU Node 02"),
            ]

        with Cluster("Worker Coordinator Node (Port 8001)"):
            coord = Server("Worker Coordinator\n(High Concurrency)")
            with Cluster("Mounted Interfaces"):
                coord_ifaces = FastAPI(
                    "Active:\n/v1/nodes (Registration)\n/v1/jobs (Lease/Status)\n/v1/logs (Log Streaming)\n/v1/collateral (CAS Fetch)\n\nBlocked: Runs, Webhooks, MCP"
                )

        with Cluster("Central Storage & Queues"):
            db = Postgresql("Cluster DB & Leases")
            cas = Storage("CAS Collateral Cache")

        for node in gpu_nodes + cpu_nodes:
            node >> Edge(label="Heartbeat & Lease") >> coord
            node >> Edge(label="Chunked Logs") >> coord

        coord - coord_ifaces
        coord_ifaces >> db
        coord_ifaces >> cas


def generate_analytics_diagram() -> None:
    """Generate architecture diagram for Dedicated FinOps & Analytics node."""
    out_file = str(OUTPUT_DIR / "analytics_node")
    graph_attr = {
        "fontsize": "14",
        "bgcolor": "transparent",
        "pad": "0.5",
    }
    with Diagram(
        "FinOps Analytics & Telemetry Node (role=analytics)",
        show=False,
        filename=out_file,
        outformat="png",
        graph_attr=graph_attr,
        direction="LR",
    ):
        with Cluster("Consumers & BI"):
            finops = User("FinOps Analyst")
            grafana = Grafana("Grafana Dashboards")
            prom = Prometheus("Metrics Scrapers")

        with Cluster("Analytics Node (Port 8002)"):
            node = Server("Analytics Controller")
            with Cluster("Zero-Copy Columnar Engine"):
                polars = Python("Polars & Apache Arrow\nProjections Engine")
                ifaces = FastAPI(
                    "Active:\n/v1/budget/report\n/v1/cluster/metrics\n(JSON, Parquet, Arrow IPC, CSV)\n\nBlocked: Runs, Jobs, Nodes, Webhooks"
                )

        with Cluster("Data Sources"):
            db = Postgresql("PostgreSQL Ledger &\nDead-Letter Records")

        finops >> Edge(label="Export Parquet/CSV") >> node
        grafana >> Edge(label="JSON Aggregates") >> node
        prom >> Edge(label="Telemetry Queries") >> node
        node - polars
        polars - ifaces
        ifaces >> Edge(label="Read-Only Projections") >> db


def generate_mcp_diagram() -> None:
    """Generate architecture diagram for Dedicated MCP AI Assistant node."""
    out_file = str(OUTPUT_DIR / "mcp_node")
    graph_attr = {
        "fontsize": "14",
        "bgcolor": "transparent",
        "pad": "0.5",
    }
    with Diagram(
        "AI Assistant MCP Driving Adapter Node (role=mcp)",
        show=False,
        filename=out_file,
        outformat="png",
        graph_attr=graph_attr,
        direction="LR",
    ):
        with Cluster("AI Coding Assistants"):
            agy = Client("Google Antigravity")
            cursor = Client("Cursor IDE")
            claude = Client("Claude Code / Desktop")

        with Cluster("MCP Gateway Node (Port 8003)"):
            srv = Server("FastMCP Server\n(SSE & Stdio Transports)")
            with Cluster("Tool Capabilities (Configurable & Sandboxed)"):
                tools = Python(
                    "FastMCP Tools:\nhq_list_jobs\nhq_submit_run\nhq_get_run_status\nhq_stream_logs\nhq_get_cluster_nodes\n\n(Read-Only Sandboxing Available)"
                )

        with Cluster("Core Engine"):
            pipeline = Rust("CQRS Execution Pipeline\n(Least Privilege Guard)")
            db = Postgresql("Cluster State")

        agy >> Edge(label="SSE /mcp/sse") >> srv
        cursor >> Edge(label="SSE /mcp/sse") >> srv
        claude >> Edge(label="stdio / subprocess") >> srv
        srv - tools
        tools >> pipeline
        pipeline >> db


def generate_distributed_cluster_diagram() -> None:
    """Generate full enterprise multi-node distributed topology diagram."""
    out_file = str(OUTPUT_DIR / "distributed_cluster")
    graph_attr = {
        "fontsize": "14",
        "bgcolor": "transparent",
        "pad": "0.5",
    }
    with Diagram(
        "Hexaqueue Distributed Multi-Node Cluster Topology",
        show=False,
        filename=out_file,
        outformat="png",
        graph_attr=graph_attr,
        direction="TB",
    ):
        with Cluster("External Clients & Ingress"):
            with Cluster("CI/CD & Developers"):
                ci = GithubActions("GitHub / GitLab CI")
                devs = Users("DevOps & Developers")
            with Cluster("AI Agents"):
                agents = Client("Antigravity / Cursor\nAI Assistants")
            with Cluster("FinOps & BI"):
                bi = Grafana("Grafana & FinOps")

        with Cluster("Demilitarized Zone (Public / Ingress Layer)"):
            gw = Server("Gateway Node\n(role=gateway, :8000)")
            mcp_node = Server("AI MCP Gateway\n(role=mcp, :8003)")

        with Cluster("Internal Private VPC (Compute & Analytics Layer)"):
            coord = Server("Worker Coordinator\n(role=worker-api, :8001)")
            analytics = Server("Analytics Engine\n(role=analytics, :8002)")

        with Cluster("Shared Infrastructure & Persistence"):
            db = Postgresql("PostgreSQL HA Cluster\n(Runs, Jobs, Budgets)")
            storage = Storage("Object Storage / S3\n(CAS Collateral & Logs)")

        with Cluster("HPC Compute Fleet (Autoscaling Pools)"):
            gpu_pool = [Rack("AWS / GCP GPU Pool"), LinuxGeneral("On-Prem GPU Cluster")]

        ci >> Edge(label="HMAC Webhooks") >> gw
        devs >> Edge(label="REST CLI Submissions") >> gw
        agents >> Edge(label="FastMCP SSE Tools") >> mcp_node
        bi >> Edge(label="Zero-Copy Parquet/JSON") >> analytics

        gw >> db
        gw >> storage
        mcp_node >> db
        analytics >> db
        coord >> db
        coord >> storage

        for worker in gpu_pool:
            worker >> Edge(label="Heartbeat / Lease / Logs") >> coord


def main() -> None:
    """Render all architecture diagrams to documentation assets."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Generating single-node diagram...")
    generate_single_node_diagram()
    logger.info("Generating gateway diagram...")
    generate_gateway_diagram()
    logger.info("Generating worker coordinator diagram...")
    generate_worker_api_diagram()
    logger.info("Generating analytics diagram...")
    generate_analytics_diagram()
    logger.info("Generating MCP assistant diagram...")
    generate_mcp_diagram()
    logger.info("Generating distributed cluster diagram...")
    generate_distributed_cluster_diagram()
    logger.info("All diagrams rendered successfully in docs/assets/topologies/!")


if __name__ == "__main__":
    main()

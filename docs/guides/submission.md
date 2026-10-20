# HPC Workload Batch Submission & Streaming Logs Guide

> How to author declarative workloads, execute multi-job pipelines on Hexaqueue, and inspect real-time streaming execution telemetry.

---

## 1. Declarative Workload Specification

Hexaqueue workloads are declared using structured YAML definitions specifying execution metadata, individual job steps, compute requirements, and topological dependency graphs.

```yaml
run:
  id: hpc-genomics-pipeline
  name: Genomics Variant Calling Workflow

jobs:
  - id: ingest-fastq
    name: ingest_sequencing_reads
    command: python -m pipeline.ingest --reads data/sample_R1.fastq.gz
    resources:
      cpu: 4
      memory: "16GB"

  - id: bwa-alignment
    name: bwa_mem_alignment
    command: bwa mem -t 8 ref/genome.fa data/sample_R1.fastq.gz > out/aligned.sam
    depends_on:
      - ingest-fastq
    resources:
      cpu: 8
      memory: "32GB"
```

---

## 2. Submitting to Cluster with `--watch`

Submit the pipeline run using `hq run submit` or `hq submit`:

```bash
hq run submit genomics_workload.yaml --watch
```

Output:
```
✓ Run 'hpc-genomics-pipeline' submitted (2 jobs)
Run completed with status: SUCCEEDED
```

---

## 3. Querying Run and Task Status

Inspect pipeline execution and individual task states using `hq status`:

```bash
# Query aggregate pipeline progress
hq status hpc-genomics-pipeline

# Query specific task state and assigned compute worker
hq status bwa-alignment
```

---

## 4. Streaming Execution Logs

Tail and stream stdout/stderr chunks in real-time or retrieve historical log buffers:

```bash
# Tail latest execution logs
hq logs bwa-alignment

# Follow live log streaming until completion
hq logs bwa-alignment --follow

# Tail the last 50 lines
hq logs bwa-alignment --tail 50
```

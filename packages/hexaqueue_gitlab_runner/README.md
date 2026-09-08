# 🦊 `hexaqueue-gitlab-runner`

> GitLab CI/CD Custom Executor Driver.

[![PyPI: hexaqueue-gitlab-runner](https://img.shields.io/pypi/v/hexaqueue-gitlab-runner.svg)](https://pypi.org/project/hexaqueue-gitlab-runner/)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![Coverage](https://codecov.io/github/TheTrueSCU/hexaqueue/graph/badge.svg?component=hexaqueue_gitlab_runner)](https://codecov.io/github/TheTrueSCU/hexaqueue)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](../../LICENSE)

---

## 🏗️ Architecture & Dependencies

```mermaid
graph TD
    subgraph S1["hexaqueue-gitlab-runner"]
        EXECUTOR["GitLab Runner Custom Executor (prepare, run, cleanup)"]
    end

    subgraph S2["Internal Dependencies"]
        HQ_CORE["hexaqueue-core"]
    end

    S1 --> HQ_CORE
```

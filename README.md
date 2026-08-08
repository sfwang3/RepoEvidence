# RepoEvidence

RepoEvidence 是一个不依赖 LLM 的 Software Evidence Engine M0 工程骨架，最小闭环为：

`Repo → Collector → Evidence/Fact → JSON`

## 安装

```bash
python -m pip install -e '.[dev]'
```

要求 Python 3.12 或更高版本。

## CLI 示例

扫描当前目录下的仓库：

```bash
repoevidence scan /path/to/repository
```

结果默认写入被扫描仓库内部的：

```text
/path/to/repository/.repoevidence/evidence.json
```

也可以从源码运行：

```bash
python -m repoevidence scan /path/to/repository
```

## 当前 M0 能力

- 提供可安装的 `repoevidence scan <repo-path>` CLI。
- 通过 `Collector` 抽象接口和显式 registry 支持扩展 Collector。
- `RepositoryMetadataCollector` 采集仓库根目录、Git 仓库存在性、HEAD commit、当前分支，以及 `pom.xml`、`build.gradle`、`package.json`、`docker-compose.yml` 是否存在。
- `Evidence` 保存原始、可追溯的观测；`Fact` 保存结构化事实，并通过 `evidence_ids` 指向依据。
- `CollectorResult` 独立承载 `evidence`、`facts`、`conflicts`、`warnings`、`errors`，由 Scanner 聚合为 JSON。
- 输出 schema 版本为 `0.1`，包含工具版本和 timezone-aware UTC 扫描时间。
- Evidence ID 使用稳定的 `ev.` 前缀，Fact ID 使用稳定的 `fact.` 前缀；Fact 和 Conflict 的引用会在聚合时校验。

## 当前明确不包含

M0 不包含 LLM、RAG、文档生成功能、Spring API 扫描、MySQL、Flyway 或 Web UI。

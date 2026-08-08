import hashlib
import json
from pathlib import Path

import repoevidence.collectors.maven_project as maven_project
from repoevidence.collectors.maven_project import MavenProjectCollector
from repoevidence.scanner import Scanner

ROOT_POM = """\
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>demo</artifactId>
  <version>${project.version.value}</version>
  <packaging>jar</packaging>
  <properties>
    <project.version.value>1.0.0</project.version.value>
    <java.version>17</java.version>
    <maven.compiler.source>17</maven.compiler.source>
    <compiler.version>3.12.1</compiler.version>
    <spring.boot.version>3.3.1</spring.boot.version>
  </properties>
  <modules>
    <module>backend</module>
    <module>missing</module>
  </modules>
  <dependencyManagement>
    <dependencies>
      <dependency>
        <groupId>org.example</groupId>
        <artifactId>managed-lib</artifactId>
        <version>2.0.0</version>
      </dependency>
    </dependencies>
  </dependencyManagement>
  <dependencies>
    <dependency>
      <groupId>com.google.guava</groupId>
      <artifactId>guava</artifactId>
      <version>33.2.0-jre</version>
      <scope>test</scope>
      <optional>true</optional>
    </dependency>
    <dependency>
      <groupId>org.example</groupId>
      <artifactId>managed-lib</artifactId>
    </dependency>
  </dependencies>
  <build>
    <plugins>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-compiler-plugin</artifactId>
        <version>${compiler.version}</version>
      </plugin>
      <plugin>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-maven-plugin</artifactId>
        <version>${spring.boot.version}</version>
      </plugin>
    </plugins>
  </build>
</project>
"""

BACKEND_POM = """\
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <parent>
    <groupId>com.example</groupId>
    <artifactId>demo</artifactId>
    <version>1.0.0</version>
    <relativePath>../pom.xml</relativePath>
  </parent>
  <artifactId>backend</artifactId>
  <modules>
    <module>nested</module>
  </modules>
</project>
"""

NESTED_POM = """\
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <artifactId>nested</artifactId>
</project>
"""


def write_fixture(root: Path, *, root_pom: str = ROOT_POM) -> None:
    files = {
        "pom.xml": root_pom,
        "backend/pom.xml": BACKEND_POM,
        "backend/nested/pom.xml": NESTED_POM,
        "target/ignored/pom.xml": ROOT_POM,
    }
    for relative_path, content in files.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def facts_by_prefix(result, prefix: str):
    return [fact for fact in result.facts if fact.id.startswith(prefix)]


def test_collects_project_coordinates_properties_and_baselines(tmp_path: Path) -> None:
    write_fixture(tmp_path)

    result = MavenProjectCollector().collect(tmp_path)
    project_facts = [
        fact
        for fact in facts_by_prefix(result, "fact.maven.project.")
        if fact.value["pom"] == "pom.xml"
    ]
    project_values = {fact.value["declared_field"]: fact.value for fact in project_facts}

    assert project_values["groupId"]["declared_value"] == "com.example"
    assert project_values["artifactId"]["declared_value"] == "demo"
    assert project_values["version"] == {
        "module": "pom.xml",
        "pom": "pom.xml",
        "declared_field": "version",
        "declared_value": "${project.version.value}",
        "resolved_value": "1.0.0",
    }
    assert project_values["packaging"]["declared_value"] == "jar"

    properties = facts_by_prefix(result, "fact.maven.property.")
    property_values = {fact.value["name"]: fact.value for fact in properties}
    assert property_values["java.version"]["resolved_value"] == "17"
    assert property_values["project.version.value"]["raw_value"] == "1.0.0"

    baselines = facts_by_prefix(result, "fact.maven.java_baseline.")
    baseline_values = {fact.value["source"]: fact.value for fact in baselines}
    assert baseline_values["java.version"]["resolved_value"] == "17"
    assert baseline_values["maven.compiler.source"]["resolved_value"] == "17"
    assert result.conflicts == []


def test_collects_dependencies_management_plugins_and_missing_version(tmp_path: Path) -> None:
    write_fixture(tmp_path)

    result = MavenProjectCollector().collect(tmp_path)
    dependencies = facts_by_prefix(result, "fact.maven.dependency.")
    values = {
        fact.value["artifact_id"]: fact.value
        for fact in dependencies
        if fact.value["location"] == "dependencies"
    }

    assert values["guava"] == {
        "module": "pom.xml",
        "group_id": "com.google.guava",
        "artifact_id": "guava",
        "declared_version": "33.2.0-jre",
        "resolved_version": "33.2.0-jre",
        "scope": "test",
        "optional": True,
        "location": "dependencies",
    }
    guava_fact = next(
        fact
        for fact in dependencies
        if fact.value["artifact_id"] == "guava"
        and fact.value["location"] == "dependencies"
    )
    evidence_by_id = {item.id: item for item in result.evidence}
    guava_declaration_evidence = [
        evidence_by_id[evidence_id]
        for evidence_id in guava_fact.evidence_ids
        if evidence_id in evidence_by_id
    ]
    assert any(
        item.value["xml_path"].endswith("/scope")
        and item.value["raw_value"] == "test"
        for item in guava_declaration_evidence
    )
    assert any(
        item.value["xml_path"].endswith("/optional")
        and item.value["raw_value"] == "true"
        for item in guava_declaration_evidence
    )
    assert values["managed-lib"]["location"] == "dependencies"
    assert "resolved_version" not in values["managed-lib"]
    assert values["managed-lib"]["declared_version"] is None

    managed = [
        fact.value
        for fact in dependencies
        if fact.value["location"] == "dependencyManagement"
    ]
    assert managed == [{
        "module": "pom.xml",
        "group_id": "org.example",
        "artifact_id": "managed-lib",
        "declared_version": "2.0.0",
        "resolved_version": "2.0.0",
        "scope": None,
        "optional": False,
        "location": "dependencyManagement",
    }]

    plugins = facts_by_prefix(result, "fact.maven.plugin.")
    plugin_values = {fact.value["artifact_id"]: fact.value for fact in plugins}
    assert plugin_values["maven-compiler-plugin"]["declared_version"] == "${compiler.version}"
    assert plugin_values["maven-compiler-plugin"]["resolved_version"] == "3.12.1"
    assert plugin_values["spring-boot-maven-plugin"]["group_id"] == "org.springframework.boot"

    spring_boot = facts_by_prefix(result, "fact.maven.spring_boot.")
    assert {fact.value["source"] for fact in spring_boot} == {
        "maven_plugin_version",
    }
    assert not any("target" in item.value.get("source_file", "") for item in result.evidence)


def test_collects_nested_modules_parent_relationship_and_missing_module_warning(
    tmp_path: Path,
) -> None:
    write_fixture(tmp_path)

    result = MavenProjectCollector().collect(tmp_path)
    module_facts = facts_by_prefix(result, "fact.maven.module.")
    module_values = {fact.value["module"]: fact.value for fact in module_facts}

    assert module_values["backend"] == {
        "parent": "demo",
        "module": "backend",
        "pom": "backend/pom.xml",
        "exists": True,
    }
    assert module_values["missing"] == {
        "parent": "demo",
        "module": "missing",
        "pom": "missing/pom.xml",
        "exists": False,
    }
    assert module_values["nested"]["pom"] == "backend/nested/pom.xml"
    assert any("missing/pom.xml" in warning for warning in result.warnings)

    assert any(
        fact.id.startswith("fact.maven.parent.relationship.")
        and fact.value["pom"] == "backend/pom.xml"
        and fact.value["parent_pom"] == "pom.xml"
        for fact in result.facts
    )
    assert any(
        fact.id.startswith("fact.maven.project.")
        and fact.value["pom"] == "backend/nested/pom.xml"
        for fact in result.facts
    )
    backend_project_fields = {
        fact.value["declared_field"]
        for fact in result.facts
        if fact.id.startswith("fact.maven.project.")
        and fact.value["pom"] == "backend/pom.xml"
    }
    assert "groupId" not in backend_project_fields
    assert "version" not in backend_project_fields


def test_non_maven_repository_returns_no_maven_facts(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("not Maven", encoding="utf-8")

    result = MavenProjectCollector().collect(tmp_path)

    assert result.evidence == []
    assert result.facts == []
    assert result.warnings == []
    assert result.errors == []


def test_malformed_and_untrusted_xml_become_warnings_without_expansion(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed" / "pom.xml"
    malformed.parent.mkdir()
    malformed.write_text("<project><artifactId>broken", encoding="utf-8")
    untrusted = tmp_path / "untrusted" / "pom.xml"
    untrusted.parent.mkdir()
    untrusted.write_text(
        """<!DOCTYPE project [<!ENTITY xxe SYSTEM \"file:///etc/passwd\">]>
<project><artifactId>&xxe;</artifactId></project>""",
        encoding="utf-8",
    )

    result = MavenProjectCollector().collect(tmp_path)

    assert result.errors == []
    assert len(result.facts) == 0
    assert any("malformed/pom.xml" in warning for warning in result.warnings)
    assert any("untrusted/pom.xml" in warning for warning in result.warnings)
    assert all("root:x:" not in json.dumps(evidence.value) for evidence in result.evidence)


def test_oversized_pom_is_skipped_with_warning(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(maven_project, "MAX_POM_BYTES", 32)
    (tmp_path / "pom.xml").write_text("<project>" + ("x" * 64) + "</project>", encoding="utf-8")

    result = MavenProjectCollector().collect(tmp_path)

    assert result.facts == []
    assert any("size limit" in warning for warning in result.warnings)


def test_distinct_baseline_sources_do_not_create_pseudo_conflict(tmp_path: Path) -> None:
    root_pom = ROOT_POM.replace(
        "    <maven.compiler.source>17</maven.compiler.source>",
        "    <maven.compiler.source>11</maven.compiler.source>\n"
        "    <maven.compiler.target>8</maven.compiler.target>",
        1,
    )
    write_fixture(tmp_path, root_pom=root_pom)

    result = MavenProjectCollector().collect(tmp_path)

    assert not any("java.version" in conflict.message for conflict in result.conflicts)
    assert not any("maven.compiler.source" in conflict.message for conflict in result.conflicts)


def test_spring_boot_parent_and_plugin_versions_are_separate_facts(tmp_path: Path) -> None:
    pom = """\
<project>
  <parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>3.2.0</version>
  </parent>
  <artifactId>boot-app</artifactId>
  <build><plugins><plugin>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-maven-plugin</artifactId>
    <version>3.3.0</version>
  </plugin></plugins></build>
</project>
"""
    (tmp_path / "pom.xml").write_text(pom, encoding="utf-8")

    result = MavenProjectCollector().collect(tmp_path)
    spring_boot = facts_by_prefix(result, "fact.maven.spring_boot.")

    assert {fact.value["source"] for fact in spring_boot} == {
        "parent_version",
        "maven_plugin_version",
    }
    assert result.conflicts == []


def test_repeated_spring_boot_plugins_keep_all_occurrence_evidence(tmp_path: Path) -> None:
    plugin = """\
<plugin>
  <groupId>org.springframework.boot</groupId>
  <artifactId>spring-boot-maven-plugin</artifactId>
  <version>3.3.0</version>
</plugin>
"""
    pom = (
        "<project><artifactId>repeated</artifactId><build><plugins>"
        + plugin * 3
        + "</plugins></build></project>"
    )
    (tmp_path / "pom.xml").write_text(pom, encoding="utf-8")

    result = MavenProjectCollector().collect(tmp_path)

    spring_boot = facts_by_prefix(result, "fact.maven.spring_boot.")
    assert result.errors == []
    assert len(spring_boot) == 3
    assert all(fact.evidence_ids for fact in spring_boot)


def test_evidence_has_hash_location_and_reference_integrity(tmp_path: Path) -> None:
    write_fixture(tmp_path)

    result = MavenProjectCollector().collect(tmp_path)
    evidence = {item.id: item for item in result.evidence}
    root_hash = hashlib.sha256((tmp_path / "pom.xml").read_bytes()).hexdigest()

    pom_evidence = evidence["ev.maven.pom.pom.xml"]
    assert pom_evidence.value == {
        "source_file": "pom.xml",
        "sha256": root_hash,
        "xml_path": "/project",
        "module": "pom.xml",
        "raw_value": None,
    }
    assert all(item.value["source_file"] != "target/ignored/pom.xml" for item in evidence.values())
    assert all(item.id.startswith("ev.maven.") for item in result.evidence)
    assert all(item.id.startswith("fact.maven.") for item in result.facts)
    assert all(ref in evidence for fact in result.facts for ref in fact.evidence_ids)
    assert all(ref in evidence for conflict in result.conflicts for ref in conflict.evidence_ids)


def test_semantic_ids_survive_unrelated_dependency_insertion(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    write_fixture(first)
    inserted = ROOT_POM.replace(
        "  <dependencies>\n",
        "  <dependencies>\n    <dependency><groupId>org.unrelated</groupId>"
        "<artifactId>new-lib</artifactId><version>1</version></dependency>\n",
        1,
    )
    write_fixture(second, root_pom=inserted)

    first_result = MavenProjectCollector().collect(first)
    second_result = MavenProjectCollector().collect(second)
    first_ids = {
        item.id
        for item in [*first_result.evidence, *first_result.facts]
        if "guava" in item.id or "maven-compiler-plugin" in item.id
    }
    second_ids = {
        item.id
        for item in [*second_result.evidence, *second_result.facts]
        if "guava" in item.id or "maven-compiler-plugin" in item.id
    }

    assert first_ids == second_ids


def test_same_semantic_declarations_use_local_occurrence_and_conflict(tmp_path: Path) -> None:
    duplicate = ROOT_POM.replace(
        "  <groupId>com.example</groupId>\n",
        "  <groupId>com.example</groupId>\n  <groupId>com.other</groupId>\n",
        1,
    )
    write_fixture(tmp_path, root_pom=duplicate)

    result = MavenProjectCollector().collect(tmp_path)
    group_facts = [
        fact
        for fact in result.facts
        if fact.value.get("declared_field") == "groupId"
    ]

    assert len(group_facts) == 2
    assert group_facts[0].id != group_facts[1].id
    assert any(conflict.id.startswith("conflict.maven.") for conflict in result.conflicts)


def test_default_scanner_runs_maven_after_spring(tmp_path: Path) -> None:
    write_fixture(tmp_path)

    result = Scanner.default().scan(tmp_path)

    assert result.collectors == [
        "repository_metadata",
        "spring_api",
        "maven_project",
        "flyway_migration",
    ]
    assert any(fact.id.startswith("fact.maven.project.") for fact in result.facts)

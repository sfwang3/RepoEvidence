import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote
from xml.etree.ElementTree import Element, ParseError

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

from repoevidence.collectors.base import Collector
from repoevidence.models import CollectorResult, Conflict, Evidence, Fact

MAX_POM_BYTES = 5 * 1024 * 1024
_PROPERTY_PATTERN = re.compile(r"\$\{([^{}]+)\}")
_SKIPPED_DIRECTORIES = {".git", ".repoevidence", "target"}
_PROJECT_FIELDS = {
    "groupId": "group_id",
    "artifactId": "artifact_id",
    "version": "version",
    "packaging": "packaging",
}
_BASELINE_PROPERTIES = {
    "java.version",
    "maven.compiler.source",
    "maven.compiler.target",
    "maven.compiler.release",
}


@dataclass(frozen=True)
class _ParsedPom:
    relative_path: str
    path: Path
    root: Element
    sha256: str
    xml_paths: dict[int, str]


@dataclass
class _DeclarationRecord:
    comparable_value: str | None
    evidence_id: str
    fact_id: str


@dataclass
class _CollectionContext:
    root: Path
    result: CollectorResult = field(default_factory=CollectorResult)
    evidence_occurrences: dict[tuple[str, str, str], int] = field(default_factory=dict)
    fact_occurrences: dict[tuple[str, str, str], int] = field(default_factory=dict)
    semantic_declarations: dict[tuple[str, str], list[_DeclarationRecord]] = field(
        default_factory=dict
    )

    def add_pom_evidence(self, pom: _ParsedPom) -> str:
        evidence_id = f"ev.maven.pom.{_id_part(pom.relative_path)}"
        self.result.evidence.append(
            Evidence(
                id=evidence_id,
                kind="maven_pom",
                source=pom.relative_path,
                value={
                    "source_file": pom.relative_path,
                    "sha256": pom.sha256,
                    "xml_path": "/project",
                    "module": pom.relative_path,
                    "raw_value": None,
                },
            )
        )
        return evidence_id

    def add_evidence(
        self,
        pom: _ParsedPom,
        element: Element,
        *,
        section: str,
        semantic_key: str,
        raw_value: Any,
        resolved_value: Any = None,
        extra: dict[str, Any] | None = None,
    ) -> str:
        occurrence = self._next_occurrence(self.evidence_occurrences, pom, section, semantic_key)
        suffix = f".{occurrence}" if occurrence > 1 else ""
        evidence_id = (
            f"ev.maven.declaration.{_id_part(pom.relative_path)}."
            f"{_id_part(section)}.{_id_part(semantic_key)}{suffix}"
        )
        value: dict[str, Any] = {
            "source_file": pom.relative_path,
            "sha256": pom.sha256,
            "xml_path": pom.xml_paths[id(element)],
            "module": pom.relative_path,
            "raw_value": raw_value,
        }
        if resolved_value is not None or raw_value is not None:
            value["resolved_value"] = resolved_value
        if extra:
            value.update(extra)
        self.result.evidence.append(
            Evidence(
                id=evidence_id,
                kind="maven_declaration",
                source=pom.relative_path,
                value=value,
            )
        )
        return evidence_id

    def add_fact(
        self,
        pom: _ParsedPom,
        *,
        kind: str,
        semantic_key: str,
        name: str,
        value: Any,
        evidence_ids: list[str],
        conflict_key: str | None = None,
        comparable_value: str | None = None,
    ) -> str:
        occurrence = self._next_occurrence(self.fact_occurrences, pom, kind, semantic_key)
        suffix = f".{occurrence}" if occurrence > 1 else ""
        fact_id = (
            f"fact.maven.{_id_part(kind)}.{_id_part(pom.relative_path)}."
            f"{_id_part(semantic_key)}{suffix}"
        )
        self.result.facts.append(
            Fact(
                id=fact_id,
                name=name,
                value=value,
                status="declared",
                evidence_ids=evidence_ids,
            )
        )
        if conflict_key is not None:
            self.semantic_declarations.setdefault(
                (pom.relative_path, conflict_key), []
            ).append(
                _DeclarationRecord(
                    comparable_value=comparable_value,
                    evidence_id=evidence_ids[0],
                    fact_id=fact_id,
                )
            )
        return fact_id

    @staticmethod
    def _next_occurrence(
        occurrences: dict[tuple[str, str, str], int],
        pom: _ParsedPom,
        section: str,
        semantic_key: str,
    ) -> int:
        key = (pom.relative_path, section, semantic_key)
        occurrence = occurrences.get(key, 0) + 1
        occurrences[key] = occurrence
        return occurrence


class MavenProjectCollector(Collector):
    """Collect deterministic, declaration-only facts from Maven POM files."""

    name = "maven_project"

    def collect(self, repo_root: Path) -> CollectorResult:
        root = repo_root.resolve()
        self._active_root = root
        context = _CollectionContext(root=root)
        parsed_poms = self._read_poms(root, context)
        parsed_by_path = {pom.relative_path: pom for pom in parsed_poms}

        for pom in parsed_poms:
            self._collect_pom(context, pom, parsed_by_path)
        self._add_conflicts(context)
        return context.result

    def _read_poms(self, root: Path, context: _CollectionContext) -> list[_ParsedPom]:
        paths = self._pom_paths(root)
        parsed: list[_ParsedPom] = []
        for path in paths:
            relative_path = path.relative_to(root).as_posix()
            try:
                with path.open("rb") as stream:
                    source_bytes = stream.read(MAX_POM_BYTES + 1)
            except (OSError, UnicodeError) as exc:
                context.result.warnings.append(f"Unable to read Maven POM {relative_path}: {exc}")
                continue
            if len(source_bytes) > MAX_POM_BYTES:
                context.result.warnings.append(
                    f"Maven POM {relative_path} exceeds the {MAX_POM_BYTES}-byte size limit; "
                    "skipped."
                )
                continue

            try:
                root_element = SafeET.fromstring(source_bytes)
            except (DefusedXmlException, ParseError, ValueError) as exc:
                context.result.warnings.append(
                    f"Unable to parse Maven POM {relative_path}: {type(exc).__name__}: {exc}"
                )
                continue
            if _local_name(root_element.tag) != "project":
                context.result.warnings.append(
                    f"Maven POM {relative_path} has a non-project root element; skipped."
                )
                continue
            parsed.append(
                _ParsedPom(
                    relative_path=relative_path,
                    path=path,
                    root=root_element,
                    sha256=hashlib.sha256(source_bytes).hexdigest(),
                    xml_paths=_xml_paths(root_element),
                )
            )
        return parsed

    @staticmethod
    def _pom_paths(root: Path) -> list[Path]:
        paths: list[Path] = []
        for current, directory_names, file_names in os.walk(root, followlinks=False):
            current_path = Path(current)
            directory_names[:] = sorted(
                directory_name
                for directory_name in directory_names
                if directory_name not in _SKIPPED_DIRECTORIES
                and not (current_path / directory_name).is_symlink()
            )
            if "pom.xml" in file_names:
                path = current_path / "pom.xml"
                if not path.is_symlink() and path.is_file():
                    paths.append(path)
        return sorted(paths, key=lambda path: path.relative_to(root).as_posix())

    def _collect_pom(
        self,
        context: _CollectionContext,
        pom: _ParsedPom,
        parsed_by_path: dict[str, _ParsedPom],
    ) -> None:
        pom_evidence_id = context.add_pom_evidence(pom)
        properties, property_evidence = self._collect_properties(context, pom, pom_evidence_id)
        self._collect_project_fields(context, pom, pom_evidence_id, properties)
        self._collect_java_baselines(context, pom, property_evidence, properties)
        self._collect_parent(context, pom, parsed_by_path, properties, pom_evidence_id)
        self._collect_modules(context, pom, parsed_by_path, properties, pom_evidence_id)
        self._collect_dependencies(context, pom, properties, pom_evidence_id)
        self._collect_plugins(context, pom, properties, pom_evidence_id)

    def _collect_properties(
        self,
        context: _CollectionContext,
        pom: _ParsedPom,
        pom_evidence_id: str,
    ) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
        section = _direct_child(pom.root, "properties")
        if section is None:
            return {}, {}
        declarations: dict[str, list[str]] = {}
        evidence_ids: dict[str, list[str]] = {}
        elements: list[tuple[str, str, Element]] = []
        for property_element in list(section):
            name = _local_name(property_element.tag)
            raw_value = _text(property_element)
            declarations.setdefault(name, []).append(raw_value)
            elements.append((name, raw_value, property_element))
        for name, raw_value, property_element in elements:
            resolved_value = _resolve_value(raw_value, declarations)
            evidence_id = context.add_evidence(
                pom,
                property_element,
                section="properties",
                semantic_key=name,
                raw_value=raw_value,
                resolved_value=resolved_value,
                extra={"name": name},
            )
            context.add_fact(
                pom,
                kind="property",
                semantic_key=name,
                name=f"Maven property {name}",
                value={
                    "module": pom.relative_path,
                    "pom": pom.relative_path,
                    "name": name,
                    "raw_value": raw_value,
                    "resolved_value": resolved_value,
                },
                evidence_ids=[evidence_id, pom_evidence_id],
                conflict_key=f"property:{name}",
                comparable_value=resolved_value if len(declarations[name]) == 1 else None,
            )
            evidence_ids.setdefault(name, []).append(evidence_id)
        return declarations, evidence_ids

    def _collect_project_fields(
        self,
        context: _CollectionContext,
        pom: _ParsedPom,
        pom_evidence_id: str,
        properties: dict[str, list[str]],
    ) -> None:
        for xml_name, field_name in _PROJECT_FIELDS.items():
            for element in _direct_children(pom.root, xml_name):
                raw_value = _text(element)
                resolved_value = _resolve_value(raw_value, properties)
                evidence_id = context.add_evidence(
                    pom,
                    element,
                    section="project",
                    semantic_key=field_name,
                    raw_value=raw_value,
                    resolved_value=resolved_value,
                )
                value = {
                    "module": pom.relative_path,
                    "pom": pom.relative_path,
                    "declared_field": xml_name,
                    "declared_value": raw_value,
                    "resolved_value": resolved_value,
                }
                context.add_fact(
                    pom,
                    kind="project",
                    semantic_key=field_name,
                    name=f"Maven project declared {xml_name}",
                    value=value,
                    evidence_ids=[evidence_id, pom_evidence_id],
                    conflict_key=f"project:{field_name}",
                    comparable_value=resolved_value,
                )

    def _collect_java_baselines(
        self,
        context: _CollectionContext,
        pom: _ParsedPom,
        property_evidence: dict[str, list[str]],
        properties: dict[str, list[str]],
    ) -> None:
        for name in sorted(_BASELINE_PROPERTIES):
            for ordinal, raw_value in enumerate(properties.get(name, [])):
                resolved_value = _resolve_value(raw_value, properties)
                evidence_ids = [*property_evidence.get(name, [])[ordinal : ordinal + 1]]
                if not evidence_ids:
                    continue
                context.add_fact(
                    pom,
                    kind="java_baseline",
                    semantic_key=name,
                    name=f"Java baseline declaration {name}",
                    value={
                        "module": pom.relative_path,
                        "pom": pom.relative_path,
                        "source": name,
                        "declared_value": raw_value,
                        "resolved_value": resolved_value,
                    },
                    evidence_ids=evidence_ids,
                )

    def _collect_parent(
        self,
        context: _CollectionContext,
        pom: _ParsedPom,
        parsed_by_path: dict[str, _ParsedPom],
        properties: dict[str, list[str]],
        pom_evidence_id: str,
    ) -> None:
        parent = _direct_child(pom.root, "parent")
        if parent is None:
            return
        coordinates: dict[str, tuple[str | None, str | None, str]] = {}
        evidence_ids: list[str] = []
        field_evidence_ids: dict[str, str] = {}
        for xml_name, field_name in (
            ("groupId", "group_id"),
            ("artifactId", "artifact_id"),
            ("version", "version"),
            ("relativePath", "relative_path"),
        ):
            element = _direct_child(parent, xml_name)
            if element is None:
                continue
            raw_value = _text(element)
            resolved_value = _resolve_value(raw_value, properties)
            coordinates[field_name] = (raw_value, resolved_value, xml_name)
            evidence_id = context.add_evidence(
                pom,
                element,
                section="parent",
                semantic_key=field_name,
                raw_value=raw_value,
                resolved_value=resolved_value,
            )
            evidence_ids.append(evidence_id)
            field_evidence_ids[field_name] = evidence_id
        context.add_fact(
            pom,
            kind="parent",
            semantic_key="declaration",
            name="Maven parent declaration",
            value={
                "module": pom.relative_path,
                "pom": pom.relative_path,
                **{
                    f"declared_{field_name}": raw_value
                    for field_name, (raw_value, _, _) in coordinates.items()
                },
                **{
                    f"resolved_{field_name}": resolved_value
                    for field_name, (_, resolved_value, _) in coordinates.items()
                },
            },
            evidence_ids=[*evidence_ids, pom_evidence_id],
        )

        parent_group = coordinates.get("group_id", (None, None, ""))[1]
        parent_artifact_value = coordinates.get("artifact_id", (None, None, ""))[1]
        parent_version = coordinates.get("version", (None, None, ""))
        if (
            parent_group == "org.springframework.boot"
            and parent_artifact_value == "spring-boot-starter-parent"
            and parent_version[1] is not None
        ):
            context.add_fact(
                pom,
                kind="spring_boot",
                semantic_key="parent_version",
                name="Spring Boot parent version",
                value={
                    "module": pom.relative_path,
                    "pom": pom.relative_path,
                    "source": "parent_version",
                    "declared_value": parent_version[0],
                    "resolved_value": parent_version[1],
                },
                evidence_ids=[field_evidence_ids["version"]],
            )

        relative_path = coordinates.get("relative_path", ("../pom.xml", "../pom.xml", ""))[1]
        parent_path = self._resolve_pom_reference(pom, relative_path)
        if parent_path is None:
            return
        parent_relative_path = parent_path.relative_to(context.root).as_posix()
        if parent_relative_path not in parsed_by_path:
            return
        parent_artifact = _direct_child(parsed_by_path[parent_relative_path].root, "artifactId")
        parent_name = (
            _text(parent_artifact) if parent_artifact is not None else parent_relative_path
        )
        relation_element = _direct_child(parent, "relativePath")
        if relation_element is None:
            relation_element = parent
        relation_evidence = context.add_evidence(
            pom,
            relation_element,
            section="parent",
            semantic_key="relationship",
            raw_value=parent_relative_path,
            extra={"parent_pom": parent_relative_path, "exists": True},
        )
        context.add_fact(
            pom,
            kind="parent.relationship",
            semantic_key=parent_relative_path,
            name="Maven parent relationship",
            value={
                "module": pom.relative_path,
                "pom": pom.relative_path,
                "parent": parent_name,
                "parent_pom": parent_relative_path,
            },
            evidence_ids=[relation_evidence, *evidence_ids],
        )

    def _collect_modules(
        self,
        context: _CollectionContext,
        pom: _ParsedPom,
        parsed_by_path: dict[str, _ParsedPom],
        properties: dict[str, list[str]],
        pom_evidence_id: str,
    ) -> None:
        modules = _direct_child(pom.root, "modules")
        if modules is None:
            return
        parent_artifact = _direct_child(pom.root, "artifactId")
        parent_name = _text(parent_artifact) if parent_artifact is not None else pom.relative_path
        for module_element in _direct_children(modules, "module"):
            raw_module = _text(module_element)
            resolved_module = _resolve_value(raw_module, properties)
            resolved_module = resolved_module if resolved_module is not None else raw_module
            module_path = self._resolve_module_path(pom, resolved_module)
            module_relative_path = (
                module_path.relative_to(context.root).as_posix() if module_path else None
            )
            exists = module_path is not None and module_path.is_file()
            expected_pom = module_relative_path or f"{resolved_module.rstrip('/')}/pom.xml"
            evidence_id = context.add_evidence(
                pom,
                module_element,
                section="modules",
                semantic_key=expected_pom,
                raw_value=raw_module,
                resolved_value=resolved_module,
                extra={"pom": expected_pom, "exists": exists},
            )
            context.add_fact(
                pom,
                kind="module",
                semantic_key=expected_pom,
                name="Maven module declaration",
                value={
                    "parent": parent_name,
                    "module": raw_module,
                    "pom": expected_pom,
                    "exists": exists,
                },
                evidence_ids=[evidence_id, pom_evidence_id],
            )
            if not exists:
                context.result.warnings.append(
                    f"Maven module {raw_module!r} in {pom.relative_path} points to missing "
                    f"{expected_pom}."
                )
            elif module_relative_path not in parsed_by_path:
                context.result.warnings.append(
                    f"Maven module {raw_module!r} in {pom.relative_path} does not contain a "
                    "valid Maven project POM."
                )

    def _collect_dependencies(
        self,
        context: _CollectionContext,
        pom: _ParsedPom,
        properties: dict[str, list[str]],
        pom_evidence_id: str,
    ) -> None:
        sections = (
            ("dependencies", _direct_child(pom.root, "dependencies")),
            ("dependencyManagement", _direct_child(pom.root, "dependencyManagement")),
        )
        for location, section in sections:
            if location == "dependencyManagement":
                section = _direct_child(section, "dependencies") if section is not None else None
            if section is None:
                continue
            for dependency in _direct_children(section, "dependency"):
                fields = self._dependency_fields(dependency, properties)
                group_id = fields["group_id"][1]
                artifact_id = fields["artifact_id"][1]
                raw_group = fields["group_id"][0]
                raw_artifact = fields["artifact_id"][0]
                semantic_key = f"{location}:{raw_group}:{raw_artifact}"
                evidence_id = context.add_evidence(
                    pom,
                    dependency,
                    section=location,
                    semantic_key=semantic_key,
                    raw_value={
                        "group_id": raw_group,
                        "artifact_id": raw_artifact,
                    },
                    extra={"location": location},
                )
                version_raw, version_resolved, version_evidence = self._field_evidence(
                    context, pom, dependency, fields, location, semantic_key, "version"
                )
                _, _, scope_evidence = self._field_evidence(
                    context, pom, dependency, fields, location, semantic_key, "scope"
                )
                _, _, optional_evidence = self._field_evidence(
                    context, pom, dependency, fields, location, semantic_key, "optional"
                )
                evidence_ids = [
                    evidence_id,
                    *version_evidence,
                    *scope_evidence,
                    *optional_evidence,
                    pom_evidence_id,
                ]
                value: dict[str, Any] = {
                    "module": pom.relative_path,
                    "group_id": group_id,
                    "artifact_id": artifact_id,
                    "declared_version": version_raw,
                    "scope": fields["scope"][1] or fields["scope"][0],
                    "optional": (fields["optional"][1] or fields["optional"][0]) == "true",
                    "location": location,
                }
                if version_raw is not None and version_resolved is not None:
                    value["resolved_version"] = version_resolved
                context.add_fact(
                    pom,
                    kind="dependency",
                    semantic_key=semantic_key,
                    name=f"Maven {location} dependency declaration",
                    value=value,
                    evidence_ids=evidence_ids,
                    conflict_key=f"{location}:dependency:{raw_group}:{raw_artifact}",
                    comparable_value=version_resolved,
                )

    def _dependency_fields(
        self, dependency: Element, properties: dict[str, list[str]]
    ) -> dict[str, tuple[str | None, str | None, Element | None]]:
        fields: dict[str, tuple[str | None, str | None, Element | None]] = {}
        for name in ("groupId", "artifactId", "version", "scope", "optional"):
            element = _direct_child(dependency, name)
            raw_value = _text(element) if element is not None else None
            fields[name_to_field(name)] = (
                raw_value,
                _resolve_value(raw_value, properties),
                element,
            )
        return fields

    def _field_evidence(
        self,
        context: _CollectionContext,
        pom: _ParsedPom,
        dependency: Element,
        fields: dict[str, tuple[str | None, str | None, Element | None]],
        location: str,
        semantic_key: str,
        field_name: str,
    ) -> tuple[str | None, str | None, list[str]]:
        raw_value, resolved_value, element = fields[field_name]
        if element is None:
            return raw_value, resolved_value, []
        evidence_id = context.add_evidence(
            pom,
            element,
            section=location,
            semantic_key=f"{semantic_key}:{field_name}",
            raw_value=raw_value,
            resolved_value=resolved_value,
        )
        return raw_value, resolved_value, [evidence_id]

    def _collect_plugins(
        self,
        context: _CollectionContext,
        pom: _ParsedPom,
        properties: dict[str, list[str]],
        pom_evidence_id: str,
    ) -> None:
        build = _direct_child(pom.root, "build")
        plugins_section = _direct_child(build, "plugins") if build is not None else None
        if plugins_section is None:
            return
        for plugin in _direct_children(plugins_section, "plugin"):
            fields: dict[str, tuple[str | None, str | None, Element | None]] = {}
            for name in ("groupId", "artifactId", "version"):
                element = _direct_child(plugin, name)
                raw_value = _text(element) if element is not None else None
                fields[name_to_field(name)] = (
                    raw_value,
                    _resolve_value(raw_value, properties),
                    element,
                )
            raw_group, group_id, group_element = fields["group_id"]
            raw_artifact, artifact_id, artifact_element = fields["artifact_id"]
            raw_version, version, version_element = fields["version"]
            semantic_key = f"{raw_group}:{raw_artifact}"
            evidence_id = context.add_evidence(
                pom,
                plugin,
                section="plugins",
                semantic_key=semantic_key,
                raw_value={"group_id": raw_group, "artifact_id": raw_artifact},
            )
            evidence_ids = [evidence_id]
            plugin_version_evidence: str | None = None
            for field_name, element, raw_value, resolved_value in (
                ("group_id", group_element, raw_group, group_id),
                ("artifact_id", artifact_element, raw_artifact, artifact_id),
                ("version", version_element, raw_version, version),
                ):
                if element is not None:
                    field_evidence_id = context.add_evidence(
                        pom,
                        element,
                        section="plugins",
                        semantic_key=f"{semantic_key}:{field_name}",
                        raw_value=raw_value,
                        resolved_value=resolved_value,
                    )
                    evidence_ids.append(field_evidence_id)
                    if field_name == "version":
                        plugin_version_evidence = field_evidence_id
            value: dict[str, Any] = {
                "module": pom.relative_path,
                "group_id": group_id,
                "artifact_id": artifact_id,
                "declared_version": raw_version,
            }
            if raw_version is not None and version is not None:
                value["resolved_version"] = version
            context.add_fact(
                pom,
                kind="plugin",
                semantic_key=semantic_key,
                name="Maven build plugin declaration",
                value=value,
                evidence_ids=[*evidence_ids, pom_evidence_id],
                conflict_key=f"plugin:{raw_group}:{raw_artifact}",
                comparable_value=version,
            )
            if (
                group_id == "org.springframework.boot"
                and artifact_id == "spring-boot-maven-plugin"
                and version is not None
                and plugin_version_evidence is not None
            ):
                context.add_fact(
                    pom,
                    kind="spring_boot",
                    semantic_key="maven_plugin_version",
                    name="Spring Boot Maven plugin version",
                    value={
                        "module": pom.relative_path,
                        "pom": pom.relative_path,
                        "source": "maven_plugin_version",
                        "declared_value": raw_version,
                        "resolved_value": version,
                    },
                    evidence_ids=[plugin_version_evidence],
                )

    def _resolve_module_path(self, pom: _ParsedPom, module: str) -> Path | None:
        candidate = (pom.path.parent / module).resolve()
        if candidate.name != "pom.xml":
            candidate = candidate / "pom.xml"
        try:
            candidate.relative_to(self._root_for_path(pom))
        except ValueError:
            return None
        return candidate

    def _resolve_pom_reference(self, pom: _ParsedPom, relative_path: str | None) -> Path | None:
        if not relative_path:
            return None
        candidate = (pom.path.parent / relative_path).resolve()
        if candidate.is_dir():
            candidate = candidate / "pom.xml"
        try:
            candidate.relative_to(self._root_for_path(pom))
        except ValueError:
            return None
        return candidate if candidate.is_file() else None

    def _root_for_path(self, pom: _ParsedPom) -> Path:
        return self._active_root

    @staticmethod
    def _add_conflicts(context: _CollectionContext) -> None:
        for (module, semantic_key), records in sorted(context.semantic_declarations.items()):
            comparable_values = {record.comparable_value for record in records}
            if len(records) < 2 or None in comparable_values or len(comparable_values) < 2:
                continue
            conflict_id = f"conflict.maven.{_id_part(module)}.{_id_part(semantic_key)}"
            context.result.conflicts.append(
                Conflict(
                    id=conflict_id,
                    message=(
                        f"Multiple incompatible Maven declarations for {semantic_key} "
                        f"in {module}: {sorted(comparable_values)}"
                    ),
                    fact_id=records[0].fact_id,
                    evidence_ids=[record.evidence_id for record in records],
                )
            )


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _direct_child(element: Element | None, name: str) -> Element | None:
    if element is None:
        return None
    return next((child for child in list(element) if _local_name(child.tag) == name), None)


def _direct_children(element: Element | None, name: str) -> list[Element]:
    if element is None:
        return []
    return [child for child in list(element) if _local_name(child.tag) == name]


def _text(element: Element | None) -> str:
    if element is None:
        return ""
    return "".join(element.itertext()).strip()


def _xml_paths(root: Element) -> dict[int, str]:
    paths: dict[int, str] = {}

    def visit(element: Element, path: str) -> None:
        paths[id(element)] = path
        counts: dict[str, int] = {}
        for child in list(element):
            child_name = _local_name(child.tag)
            counts[child_name] = counts.get(child_name, 0) + 1
            suffix = f"[{counts[child_name]}]" if counts[child_name] > 1 else ""
            visit(child, f"{path}/{child_name}{suffix}")

    visit(root, "/project")
    return paths


def _id_part(value: str) -> str:
    return quote(value, safe="")


def name_to_field(name: str) -> str:
    return {
        "groupId": "group_id",
        "artifactId": "artifact_id",
        "version": "version",
        "scope": "scope",
        "optional": "optional",
    }[name]


def _resolve_value(raw_value: str | None, properties: dict[str, list[str]]) -> str | None:
    if raw_value is None:
        return None
    memo: dict[str, str | None] = {}

    def resolve_property(name: str, stack: tuple[str, ...]) -> str | None:
        if name in memo:
            return memo[name]
        values = properties.get(name, [])
        if len(values) != 1 or name in stack:
            return None
        resolved = resolve_text(values[0], (*stack, name))
        memo[name] = resolved
        return resolved

    def resolve_text(value: str, stack: tuple[str, ...]) -> str | None:
        matches = list(_PROPERTY_PATTERN.finditer(value))
        if not matches:
            return value
        parts: list[str] = []
        cursor = 0
        for match in matches:
            parts.append(value[cursor : match.start()])
            replacement = resolve_property(match.group(1), stack)
            if replacement is None:
                return None
            parts.append(replacement)
            cursor = match.end()
        parts.append(value[cursor:])
        return "".join(parts)

    return resolve_text(raw_value, ())

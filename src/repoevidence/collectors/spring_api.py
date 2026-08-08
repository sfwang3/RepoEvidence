import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import tree_sitter_java
from tree_sitter import Language, Parser

from repoevidence.collectors.base import Collector
from repoevidence.models import CollectorResult, Evidence, Fact

_MAPPING_METHODS = {
    "GetMapping": "GET",
    "PostMapping": "POST",
    "PutMapping": "PUT",
    "DeleteMapping": "DELETE",
    "PatchMapping": "PATCH",
}
_MAPPING_ANNOTATIONS = {*_MAPPING_METHODS, "RequestMapping"}
_IGNORED_PATH_PARTS = {".git", ".repoevidence", "build", "target"}


@dataclass(frozen=True)
class _Mapping:
    annotation_type: str
    paths: list[str] | None
    methods: list[str] | None
    evidence_id: str


class SpringApiCollector(Collector):
    """Collect static HTTP mappings from Spring RestController classes."""

    name = "spring_api"

    def collect(self, repo_root: Path) -> CollectorResult:
        root = repo_root.resolve()
        result = CollectorResult()
        seen_fact_ids: set[str] = set()

        for java_file in self._java_files(root):
            try:
                self._collect_file(root, java_file, result, seen_fact_ids)
            except (OSError, UnicodeError) as exc:
                relative_path = java_file.relative_to(root).as_posix()
                result.warnings.append(f"Unable to read Java file {relative_path}: {exc}")
            except Exception as exc:  # pragma: no cover - defensive file boundary
                relative_path = java_file.relative_to(root).as_posix()
                result.warnings.append(
                    f"Unable to inspect Java file {relative_path}: {type(exc).__name__}: {exc}"
                )
        return result

    def _collect_file(
        self,
        root: Path,
        java_file: Path,
        result: CollectorResult,
        seen_fact_ids: set[str],
    ) -> None:
        source_bytes = java_file.read_bytes()
        source_bytes.decode("utf-8")
        tree = Parser(Language(tree_sitter_java.language())).parse(source_bytes)
        relative_path = java_file.relative_to(root).as_posix()
        if tree.root_node.has_error:
            result.warnings.append(f"Java syntax error detected in {relative_path}.")
            return

        annotation_ordinal = 0

        def add_evidence(node: Any, class_name: str, method_name: str | None) -> Evidence:
            nonlocal annotation_ordinal
            annotation_ordinal += 1
            annotation_type = self._annotation_type(node)
            evidence_id = (
                "ev.spring.annotation."
                f"{quote(relative_path, safe='')}"
                f":{node.start_point[0] + 1}:{node.start_point[1] + 1}:{annotation_ordinal}"
            )
            evidence = Evidence(
                id=evidence_id,
                kind="spring_annotation",
                source=relative_path,
                value={
                    "source_file": relative_path,
                    "class_name": class_name,
                    "method_name": method_name,
                    "annotation_type": annotation_type,
                    "annotation_text": self._text(node, source_bytes),
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "arguments": self._annotation_arguments(node, source_bytes),
                },
            )
            result.evidence.append(evidence)
            return evidence

        for class_node in self._descendants(tree.root_node, "class_declaration"):
            class_name_node = class_node.child_by_field_name("name")
            class_name = (
                self._text(class_name_node, source_bytes) if class_name_node else "<anonymous>"
            )
            class_annotations = self._annotations(self._modifiers(class_node))
            rest_controller = next(
                (
                    node
                    for node in class_annotations
                    if self._annotation_type(node) == "RestController"
                ),
                None,
            )
            if rest_controller is None:
                continue

            rest_evidence = add_evidence(rest_controller, class_name, None)
            class_mappings: list[_Mapping] = []
            class_path_unknown = False
            for annotation in class_annotations:
                annotation_type = self._annotation_type(annotation)
                if annotation_type != "RequestMapping":
                    continue
                evidence = add_evidence(annotation, class_name, None)
                paths = self._mapping_paths(annotation, source_bytes)
                if paths is None:
                    class_path_unknown = True
                else:
                    class_mappings.append(
                        _Mapping(
                            annotation_type=annotation_type,
                            paths=paths,
                            methods=None,
                            evidence_id=evidence.id,
                        )
                    )

            if class_path_unknown:
                result.warnings.append(
                    f"Unable to determine a static class-level path in {relative_path} "
                    f"for {class_name}; endpoint facts skipped."
                )
                class_mappings = []
                class_mapping_unknown = True
            else:
                class_mapping_unknown = False
                if not class_mappings:
                    class_mappings = [
                        _Mapping(
                            annotation_type="",
                            paths=[""],
                            methods=None,
                            evidence_id="",
                        )
                    ]

            body = class_node.child_by_field_name("body")
            if body is None:
                continue
            for method_node in [
                child for child in body.named_children if child.type == "method_declaration"
            ]:
                method_name_node = method_node.child_by_field_name("name")
                method_name = (
                    self._text(method_name_node, source_bytes) if method_name_node else "<unknown>"
                )
                method_annotations = self._annotations(self._modifiers(method_node))
                for annotation in method_annotations:
                    annotation_type = self._annotation_type(annotation)
                    if annotation_type not in _MAPPING_ANNOTATIONS:
                        continue
                    evidence = add_evidence(annotation, class_name, method_name)
                    mapping = self._method_mapping(annotation, source_bytes, evidence.id)
                    if mapping.paths is None:
                        result.warnings.append(
                            f"Unable to determine a static path for {annotation_type} "
                            f"in {relative_path}:{annotation.start_point[0] + 1}; "
                            "endpoint fact skipped."
                        )
                        continue
                    if mapping.methods is None:
                        result.warnings.append(
                            f"{annotation_type} in {relative_path}:{annotation.start_point[0] + 1} "
                            "does not declare a single or multiple HTTP method; "
                            "endpoint fact skipped."
                        )
                        continue
                    if class_mapping_unknown:
                        continue

                    for class_mapping in class_mappings:
                        for class_path in class_mapping.paths or []:
                            evidence_ids = [rest_evidence.id]
                            if class_mapping.evidence_id:
                                evidence_ids.append(class_mapping.evidence_id)
                            evidence_ids.append(mapping.evidence_id)
                            for method in mapping.methods:
                                for method_path in mapping.paths:
                                    path = self._join_paths(class_path, method_path)
                                    fact_id = self._fact_id(
                                        relative_path,
                                        class_name,
                                        class_node.start_point[0] + 1,
                                        method_name,
                                        method,
                                        path,
                                    )
                                    if fact_id in seen_fact_ids:
                                        continue
                                    seen_fact_ids.add(fact_id)
                                    result.facts.append(
                                        Fact(
                                            id=fact_id,
                                            name=f"{method} {path}",
                                            value={
                                                "method": method,
                                                "path": path,
                                                "controller": class_name,
                                                "handler": method_name,
                                            },
                                            status="inferred",
                                            evidence_ids=evidence_ids,
                                        )
                                    )

    @staticmethod
    def _java_files(root: Path) -> list[Path]:
        files = []
        for path in root.rglob("*.java"):
            relative_parts = path.relative_to(root).parts
            if any(part in _IGNORED_PATH_PARTS for part in relative_parts):
                continue
            if any(
                relative_parts[index : index + 2] == ("src", "test")
                for index in range(len(relative_parts) - 1)
            ):
                continue
            if not any(
                relative_parts[index : index + 3] == ("src", "main", "java")
                for index in range(len(relative_parts) - 2)
            ):
                continue
            files.append(path)
        return sorted(files)

    @staticmethod
    def _descendants(node: Any, node_type: str) -> list[Any]:
        matches = []
        if node.type == node_type:
            matches.append(node)
        for child in node.named_children:
            matches.extend(SpringApiCollector._descendants(child, node_type))
        return matches

    @staticmethod
    def _annotations(modifiers: Any) -> list[Any]:
        if modifiers is None:
            return []
        return [
            child
            for child in modifiers.named_children
            if child.type in {"marker_annotation", "annotation"}
        ]

    @staticmethod
    def _modifiers(node: Any) -> Any:
        return next((child for child in node.named_children if child.type == "modifiers"), None)

    @staticmethod
    def _annotation_type(annotation: Any) -> str:
        name_node = annotation.child_by_field_name("name")
        return name_node.text.decode("utf-8") if name_node is not None else ""

    @staticmethod
    def _text(node: Any, source: bytes) -> str:
        return source[node.start_byte : node.end_byte].decode("utf-8")

    @classmethod
    def _annotation_arguments(cls, annotation: Any, source: bytes) -> dict[str, Any]:
        arguments = annotation.child_by_field_name("arguments")
        if arguments is None:
            return {}
        values: dict[str, Any] = {}
        for child in arguments.named_children:
            if child.type == "element_value_pair":
                key = child.child_by_field_name("key")
                value = child.child_by_field_name("value")
                if key is not None and value is not None:
                    values[cls._text(key, source)] = cls._text(value, source)
            else:
                values.setdefault("value", cls._text(child, source))
        return values

    @classmethod
    def _method_mapping(cls, annotation: Any, source: bytes, evidence_id: str) -> _Mapping:
        annotation_type = cls._annotation_type(annotation)
        paths = cls._mapping_paths(annotation, source)
        if annotation_type in _MAPPING_METHODS:
            methods = [_MAPPING_METHODS[annotation_type]]
        else:
            methods = cls._request_methods(annotation, source)
        return _Mapping(annotation_type, paths, methods, evidence_id)

    @classmethod
    def _mapping_paths(cls, annotation: Any, source: bytes) -> list[str] | None:
        arguments = annotation.child_by_field_name("arguments")
        if arguments is None or not arguments.named_children:
            return [""]

        pairs = {
            cls._text(child.child_by_field_name("key"), source): child.child_by_field_name("value")
            for child in arguments.named_children
            if child.type == "element_value_pair"
            and child.child_by_field_name("key") is not None
            and child.child_by_field_name("value") is not None
        }
        path_nodes = [pairs[key] for key in ("path", "value") if key in pairs]
        if path_nodes:
            values: list[str] = []
            for node in path_nodes:
                parsed = cls._string_values(node, source)
                if parsed is None:
                    return None
                values.extend(parsed)
            return cls._unique(values)

        positional = [
            child for child in arguments.named_children if child.type != "element_value_pair"
        ]
        if positional:
            if len(positional) != 1:
                return None
            return cls._string_values(positional[0], source)
        return [""]

    @classmethod
    def _request_methods(cls, annotation: Any, source: bytes) -> list[str] | None:
        arguments = annotation.child_by_field_name("arguments")
        if arguments is None:
            return None
        method_pair = next(
            (
                child
                for child in arguments.named_children
                if child.type == "element_value_pair"
                and child.child_by_field_name("key") is not None
                and cls._text(child.child_by_field_name("key"), source) == "method"
            ),
            None,
        )
        if method_pair is None:
            return None
        value = method_pair.child_by_field_name("value")
        if value is None:
            return None
        nodes = value.named_children if value.type == "element_value_array_initializer" else [value]
        methods: list[str] = []
        for node in nodes:
            if node.type != "field_access":
                return None
            object_node = node.child_by_field_name("object")
            field_node = node.child_by_field_name("field")
            if (
                object_node is None
                or field_node is None
                or cls._text(object_node, source) != "RequestMethod"
            ):
                return None
            methods.append(cls._text(field_node, source))
        return cls._unique(methods) if methods else None

    @classmethod
    def _string_values(cls, node: Any, source: bytes) -> list[str] | None:
        if node.type == "string_literal":
            raw = cls._text(node, source)
            try:
                value = ast.literal_eval(raw)
            except (SyntaxError, ValueError):
                return None
            return [value] if isinstance(value, str) else None
        if node.type == "element_value_array_initializer":
            values: list[str] = []
            for child in node.named_children:
                parsed = cls._string_values(child, source)
                if parsed is None:
                    return None
                values.extend(parsed)
            return values
        return None

    @staticmethod
    def _unique(values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))

    @staticmethod
    def _join_paths(base: str, child: str) -> str:
        base_part = base.strip("/")
        child_part = child.strip("/")
        parts = [part for part in (base_part, child_part) if part]
        path = "/" + "/".join(parts) if parts else "/"
        if child == "/" and base_part:
            path += "/"
        return path

    @staticmethod
    def _fact_id(
        relative_path: str,
        class_name: str,
        class_line: int,
        method_name: str,
        method: str,
        path: str,
    ) -> str:
        components = [relative_path, class_name, str(class_line), method_name, method, path]
        encoded = ":".join(quote(component, safe="") for component in components)
        return "fact.spring.endpoint." + encoded

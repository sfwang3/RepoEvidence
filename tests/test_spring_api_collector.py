from pathlib import Path

from repoevidence.collectors.spring_api import SpringApiCollector

USER_CONTROLLER = """
package com.acme;

import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/users")
public class UserController {
    @GetMapping("/{id}")
    public String get(String id) { return id; }

    @PostMapping(value = {"/", "/bulk"})
    public void create() {}

    @PutMapping(path = "/{id}")
    public void update() {}

    @DeleteMapping("/{id}")
    public void delete() {}

    @PatchMapping(path = {"/{id}/status", "/{id}/name"})
    public void patch() {}

    @RequestMapping(path = "/search", method = {RequestMethod.GET, RequestMethod.POST})
    public void search() {}

    @RequestMapping(path = "/single", method = RequestMethod.GET)
    public void single() {}

    @RequestMapping("/implicit")
    public void implicit() {}

    @GetMapping(API_PREFIX + "/dynamic")
    public void dynamic() {}
}
"""

HEALTH_CONTROLLER = """
package com.acme;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
class HealthController {
    @GetMapping(value = "/health")
    void health() {}
}
"""

VIEW_CONTROLLER = """
package com.acme;

import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.GetMapping;

@Controller
class ViewController {
    @GetMapping("/view")
    void view() {}
}
"""

BILLING_CONTROLLER = """
package com.acme.billing;

import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
class BillingController {
    @PostMapping(path = "/billing")
    void bill() {}
}
"""

BROKEN_CONTROLLER = """
package com.acme;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
class BrokenController {
    @GetMapping("/broken")
    void broken( {
}
"""


def write_fixture(root: Path) -> None:
    files = {
        "module-a/src/main/java/com/acme/UserController.java": USER_CONTROLLER,
        "module-a/src/main/java/com/acme/HealthController.java": HEALTH_CONTROLLER,
        "module-a/src/main/java/com/acme/ViewController.java": VIEW_CONTROLLER,
        "module-a/src/test/java/com/acme/TestController.java": HEALTH_CONTROLLER,
        "module-a/target/src/main/java/com/acme/TargetController.java": HEALTH_CONTROLLER,
        "module-b/src/main/java/com/acme/billing/BillingController.java": BILLING_CONTROLLER,
        "module-b/src/main/java/com/acme/BrokenController.java": BROKEN_CONTROLLER,
    }
    for relative_path, source in files.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")


def test_collects_static_spring_endpoints_and_source_evidence(tmp_path: Path) -> None:
    write_fixture(tmp_path)

    result = SpringApiCollector().collect(tmp_path)
    endpoint_facts = [fact for fact in result.facts if fact.id.startswith("fact.spring.endpoint.")]
    endpoint_values = {(fact.value["method"], fact.value["path"]) for fact in endpoint_facts}

    assert endpoint_values == {
        ("GET", "/api/users/{id}"),
        ("POST", "/api/users/"),
        ("POST", "/api/users/bulk"),
        ("PUT", "/api/users/{id}"),
        ("DELETE", "/api/users/{id}"),
        ("PATCH", "/api/users/{id}/status"),
        ("PATCH", "/api/users/{id}/name"),
        ("GET", "/api/users/search"),
        ("POST", "/api/users/search"),
        ("GET", "/api/users/single"),
        ("GET", "/health"),
        ("POST", "/billing"),
    }
    assert all(fact.status == "inferred" for fact in endpoint_facts)
    assert all(fact.evidence_ids for fact in endpoint_facts)
    assert all(item.id.startswith("ev.spring.") for item in result.evidence)
    assert all(item.id.startswith("fact.spring.endpoint.") for item in endpoint_facts)
    assert len({item.id for item in result.evidence}) == len(result.evidence)
    assert len({item.id for item in result.facts}) == len(result.facts)

    method_evidence = next(
        item
        for item in result.evidence
        if item.value["annotation_type"] == "GetMapping"
        and item.value["method_name"] == "get"
    )
    assert method_evidence.value["source_file"] == (
        "module-a/src/main/java/com/acme/UserController.java"
    )
    assert method_evidence.value["class_name"] == "UserController"
    assert method_evidence.value["annotation_text"] == '@GetMapping("/{id}")'
    assert method_evidence.value["start_line"] == 16
    assert method_evidence.value["end_line"] == 16


def test_skips_non_rest_controller_and_unknown_mappings(tmp_path: Path) -> None:
    write_fixture(tmp_path)

    result = SpringApiCollector().collect(tmp_path)
    fact_values = [fact.value for fact in result.facts]

    assert not any(value["path"] == "/view" for value in fact_values)
    assert not any(value["path"] == "/api/users/implicit" for value in fact_values)
    assert not any(value["path"].endswith("/dynamic") for value in fact_values)
    assert any("static" in warning.lower() for warning in result.warnings)
    assert any("method" in warning.lower() for warning in result.warnings)


def test_syntax_error_becomes_warning_and_does_not_raise(tmp_path: Path) -> None:
    write_fixture(tmp_path)

    result = SpringApiCollector().collect(tmp_path)

    assert result.errors == []
    assert any("syntax" in warning.lower() for warning in result.warnings)

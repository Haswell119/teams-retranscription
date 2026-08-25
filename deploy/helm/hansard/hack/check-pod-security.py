from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml

POD_PATHS: dict[str, tuple[str, ...]] = {
    "Deployment": ("spec", "template", "spec"),
    "StatefulSet": ("spec", "template", "spec"),
    "DaemonSet": ("spec", "template", "spec"),
    "Job": ("spec", "template", "spec"),
    "Pod": ("spec",),
}

HOST_NAMESPACES: tuple[str, ...] = ("hostNetwork", "hostPID", "hostIPC")

PLACEHOLDER = re.compile(r"\$\{[A-Z_]+\}")


class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def require(self, condition: bool, message: str) -> None:
        if not condition:
            self.failures.append(message)


def check_container(
    report: Report, where: str, container: dict[str, Any], pod_context: dict[str, Any]
) -> None:
    name = f"{where}/{container.get('name', 'unnamed')}"
    context: dict[str, Any] = container.get("securityContext") or {}
    capabilities: dict[str, Any] = context.get("capabilities") or {}
    seccomp = (context.get("seccompProfile") or pod_context.get("seccompProfile") or {}).get("type")
    limits: dict[str, Any] = (container.get("resources") or {}).get("limits") or {}

    report.require(context.get("allowPrivilegeEscalation") is False, f"{name}: allowPrivilegeEscalation")
    report.require(context.get("privileged") in (False, None), f"{name}: privileged")
    report.require("ALL" in (capabilities.get("drop") or []), f"{name}: capabilities.drop must include ALL")
    report.require(not capabilities.get("add"), f"{name}: capabilities.add present")
    report.require(context.get("readOnlyRootFilesystem") is True, f"{name}: readOnlyRootFilesystem")
    report.require(seccomp == "RuntimeDefault", f"{name}: seccompProfile is {seccomp}")
    report.require(
        context.get("runAsNonRoot", pod_context.get("runAsNonRoot")) is True, f"{name}: runAsNonRoot"
    )
    report.require(
        context.get("runAsUser", pod_context.get("runAsUser")) not in (0, None), f"{name}: runAsUser"
    )
    report.require("cpu" not in limits, f"{name}: CPU limit {limits.get('cpu')} throttles realtime audio")


def check_pod(report: Report, where: str, spec: dict[str, Any]) -> None:
    pod_context: dict[str, Any] = spec.get("securityContext") or {}
    for namespace in HOST_NAMESPACES:
        report.require(not spec.get(namespace), f"{where}: {namespace} is forbidden by the baseline")
    for volume in spec.get("volumes") or []:
        report.require("hostPath" not in volume, f"{where}: hostPath volume {volume.get('name')}")
    containers = (spec.get("initContainers") or []) + (spec.get("containers") or [])
    for container in containers:
        check_container(report, where, container, pod_context)


def check_workload(report: Report, document: dict[str, Any], source: str) -> None:
    path = POD_PATHS.get(document.get("kind", ""))
    if path is None:
        return
    node: Any = document
    for key in path:
        node = (node or {}).get(key)
    if node:
        check_pod(report, f"{source}:{document['kind']}/{document['metadata']['name']}", node)


def check_bot_template(report: Report, document: dict[str, Any], source: str) -> int:
    if document.get("kind") != "ConfigMap" or not document["metadata"]["name"].endswith("-bot"):
        return 0
    raw = next(iter(document["data"].values()))
    job: dict[str, Any] = yaml.safe_load(PLACEHOLDER.sub("placeholder-value", raw))
    report.require(job["kind"] == "Job", f"{source}: bot template is not a Job")
    check_workload(report, job, f"{source}(bot-template)")

    spec: dict[str, Any] = job["spec"]
    pod: dict[str, Any] = spec["template"]["spec"]
    annotations: dict[str, Any] = spec["template"]["metadata"]["annotations"]
    shm = next(v for v in pod["volumes"] if v["name"] == "dshm")
    container: dict[str, Any] = pod["containers"][0]
    browser_args = next(e for e in container["env"] if e["name"] == "HANSARD_BROWSER_ARGS")["value"]

    report.require(pod["restartPolicy"] == "Never", f"{source}: bot restartPolicy")
    report.require(spec["backoffLimit"] <= 1, f"{source}: bot backoffLimit")
    report.require(spec["ttlSecondsAfterFinished"] > 0, f"{source}: bot ttlSecondsAfterFinished")
    report.require(spec["activeDeadlineSeconds"] > 0, f"{source}: bot activeDeadlineSeconds")
    report.require(pod["terminationGracePeriodSeconds"] >= 60, f"{source}: bot grace period below 60s")
    report.require(pod["automountServiceAccountToken"] is False, f"{source}: bot mounts an API token")
    report.require(
        annotations.get("cluster-autoscaler.kubernetes.io/safe-to-evict") == "false",
        f"{source}: bot is evictable mid-meeting",
    )
    report.require(shm["emptyDir"].get("medium") == "Memory", f"{source}: /dev/shm is not tmpfs")
    report.require(bool(shm["emptyDir"].get("sizeLimit")), f"{source}: /dev/shm has no sizeLimit")
    report.require("--no-sandbox" in browser_args, f"{source}: chromium sandbox flags")
    report.require(
        container["resources"]["requests"]["memory"] == container["resources"]["limits"]["memory"],
        f"{source}: bot memory request must equal its limit",
    )
    for variable in container["env"]:
        report.require(
            "SECRET" not in variable["name"] and "PASSWORD" not in variable["name"],
            f"{source}: bot carries {variable['name']}",
        )
    return 1


def main(paths: list[str]) -> int:
    report = Report()
    objects = 0
    bots = 0
    for path in sorted(paths):
        source = Path(path).name
        for document in yaml.safe_load_all(Path(path).read_text()):
            if not document:
                continue
            objects += 1
            check_workload(report, document, source)
            bots += check_bot_template(report, document, source)

    print(f"  scanned {objects} objects, validated {bots} embedded bot Job templates")
    if report.failures:
        print("\n  violations:")
        for failure in report.failures:
            print(f"    - {failure}")
        return 1
    print("  PASS: restricted PSS, no CPU limits, no host namespaces, no hostPath, bot invariants hold")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

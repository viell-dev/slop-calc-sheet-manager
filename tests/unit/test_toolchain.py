"""Keep the Node that contributors and CI install equal to the checks image's Node."""

import re
from pathlib import Path

import pytest

from tools.build import ROOT

SETUP_NODE = "actions/setup-node"


def runtime_node_version(dockerfile: str) -> str:
    """Return the version of the only Node image, which must be the stage supplying `node`."""
    images = re.findall(r"^FROM\s+node:", dockerfile, re.MULTILINE | re.IGNORECASE)
    stage = re.compile(r"^FROM node:(\d+\.\d+\.\d+)-\S+ AS (\S+)$", re.MULTILINE)
    stages = list(stage.finditer(dockerfile))
    if len(images) != 1 or len(stages) != 1:
        raise ValueError("expected exactly one `FROM node:<version>-<variant> AS <stage>` image")
    version, name = stages[0][1], stages[0][2]
    copy = rf"^COPY --from={re.escape(name)} /usr/local/bin/node "
    if not re.search(copy, dockerfile, re.MULTILINE):
        raise ValueError(f"the checks image does not copy node from the {name!r} stage")
    return version


def workflow_files(directory: Path) -> list[Path]:
    return sorted([*directory.glob("*.yml"), *directory.glob("*.yaml")])


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def setup_node_inputs(workflow: str) -> list[dict[str, str]]:
    """Return the `with` inputs of each setup-node step, read from block-style YAML.

    Comments are ignored. A setup-node reference that is not a step's `uses` value, such as a
    flow-style step, raises rather than passing unchecked.
    """
    lines: list[tuple[int, bool, str]] = []
    for raw in workflow.splitlines():
        text = raw.split(" #", 1)[0].rstrip()
        content = text.lstrip()
        if not content or content.startswith("#"):
            continue
        column = len(text) - len(content)
        item = content.startswith("- ")
        if item:
            rest = content[1:]
            content = rest.lstrip()
            column += 1 + len(rest) - len(content)
        lines.append((column, item, content))

    steps: list[dict[str, str]] = []
    for start, (column, item, _) in enumerate(lines):
        if not item:
            continue
        end = start + 1
        while end < len(lines):
            next_column, next_item, _ = lines[end]
            if next_column < column or (next_column == column and next_item):
                break
            end += 1
        keys = [index for index in range(start, end) if lines[index][0] == column]
        positions = {lines[index][2].partition(":")[0]: index for index in keys}
        if "uses" not in positions:
            continue
        uses = _unquote(lines[positions["uses"]][2].partition(":")[2].strip())
        if not uses.startswith(f"{SETUP_NODE}@"):
            continue
        inputs: dict[str, str] = {}
        if "with" in positions:
            after = positions["with"] + 1
            children = lines[after : next((key for key in keys if key >= after), end)]
            for child_column, _, child in children:
                if child_column == children[0][0]:
                    key, _, value = child.partition(":")
                    inputs[key] = _unquote(value.strip())
        steps.append(inputs)

    if sum(SETUP_NODE in content for _, _, content in lines) != len(steps):
        raise ValueError("write each setup-node step in block style with a `uses:` key")
    return steps


def reads_nvmrc(inputs: dict[str, str]) -> bool:
    return inputs.get("node-version-file") == ".nvmrc" and "node-version" not in inputs


def test_nvmrc_names_the_checks_image_node() -> None:
    dockerfile = (ROOT / "ci/checks.Dockerfile").read_text(encoding="utf-8")
    nvmrc = (ROOT / ".nvmrc").read_text(encoding="utf-8")
    assert nvmrc == f"{runtime_node_version(dockerfile)}\n"


def test_workflows_install_node_from_nvmrc() -> None:
    steps = 0
    for workflow in workflow_files(ROOT / ".github/workflows"):
        for inputs in setup_node_inputs(workflow.read_text(encoding="utf-8")):
            assert reads_nvmrc(inputs), f"{workflow.name}: {inputs}"
            steps += 1
    assert steps > 0


STAGE = "FROM node:24.21.0-bookworm-slim@sha256:00 AS node\n"
COPY = "COPY --from=node /usr/local/bin/node /usr/local/bin/node\n"


def test_runtime_node_version_reads_the_copied_stage() -> None:
    assert runtime_node_version(f"{STAGE}FROM python:3.12\n{COPY}") == "24.21.0"


@pytest.mark.parametrize(
    "dockerfile",
    [
        f"FROM node:24.21.0-slim AS other\n{STAGE.replace('24.21.0', '24.22.0')}{COPY}",
        f"{STAGE}{COPY.replace('--from=node', '--from=other')}",
        f"FROM node:24.21.0-slim\n{COPY}",
    ],
    ids=["second node stage", "node copied from elsewhere", "unnamed stage"],
)
def test_runtime_node_version_rejects_ambiguous_images(dockerfile: str) -> None:
    with pytest.raises(ValueError):
        runtime_node_version(dockerfile)


def test_workflow_files_include_both_extensions(tmp_path: Path) -> None:
    for name in ("a.yml", "b.yaml", "c.txt"):
        (tmp_path / name).touch()
    assert [path.name for path in workflow_files(tmp_path)] == ["a.yml", "b.yaml"]


STEPS = """\
jobs:
  checks:
    steps:
      - uses: actions/checkout@abc # v7
      - name: Node
        uses: {uses}
        with:
{inputs}
      - run: echo done
"""


def test_setup_node_inputs_reads_only_the_steps_inputs() -> None:
    inputs = "          node-version-file: .nvmrc\n          package-manager-cache: false"
    workflow = STEPS.format(uses="actions/setup-node@abc # v7.1.0", inputs=inputs)
    assert setup_node_inputs(workflow) == [
        {"node-version-file": ".nvmrc", "package-manager-cache": "false"}
    ]


@pytest.mark.parametrize(
    ("uses", "inputs", "accepted"),
    [
        ("actions/setup-node@abc", "          node-version-file: .nvmrc", True),
        ('"actions/setup-node@abc"', "          node-version-file: '.nvmrc'", True),
        ("actions/setup-node@abc", '          node-version-file: ".nvmrc"', True),
        ("actions/setup-node@abc", "          # node-version-file: .nvmrc\n          a: b", False),
        ("actions/setup-node@abc", "", False),
        ("actions/setup-node@abc", "          node-version-file: .nvmrc-old", False),
        ("actions/setup-node@abc", '          node-version: "24.21.0"', False),
        (
            "actions/setup-node@abc",
            "          node-version-file: .nvmrc\n          node-version: 24",
            False,
        ),
    ],
    ids=[
        "unquoted",
        "single quotes",
        "double quotes",
        "commented",
        "missing",
        "other file",
        "fixed version",
        "overridden",
    ],
)
def test_setup_node_steps_must_read_nvmrc(uses: str, inputs: str, accepted: bool) -> None:
    [step] = setup_node_inputs(STEPS.format(uses=uses, inputs=inputs))
    assert reads_nvmrc(step) is accepted


def test_setup_node_inputs_ignores_other_steps_and_comments() -> None:
    workflow = "steps:\n  # - uses: actions/setup-node@abc\n  - uses: actions/checkout@abc\n"
    assert setup_node_inputs(workflow) == []


def test_setup_node_inputs_rejects_flow_style_steps() -> None:
    workflow = "steps:\n  - {uses: actions/setup-node@abc, with: {node-version: 24}}\n"
    with pytest.raises(ValueError):
        setup_node_inputs(workflow)

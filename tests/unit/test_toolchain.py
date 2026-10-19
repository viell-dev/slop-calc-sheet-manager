"""Keep the Node that contributors and CI install equal to the checks image's Node.

The workflow guard catches drift in the form this repository writes setup-node steps; it is not
a model of everything GitHub accepts. A setup-node reference must be
`actions/setup-node@<commit SHA>`, its input names must be the lowercase ASCII names the action
declares, and no mapping key or `uses` value may contain an expression. Any other spelling fails
the test, even where GitHub would run it. Node installed by other means, such as a script or
another action, is outside the guard.
"""

import re
import textwrap
from collections.abc import Hashable, Iterator
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from tools.build import ROOT

SETUP_NODE = re.compile(r"actions/setup-node@[0-9a-f]{40}")
INPUT_NAME = re.compile(r"[a-z0-9-]+")
EXPRESSION = "${{"


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


class WorkflowLoader(yaml.BaseLoader):
    """Load every scalar as a string and refuse duplicate keys.

    PyYAML's safe loader follows YAML 1.1, which reads unquoted `on`, `yes` and similar keys as
    booleans, so two such job IDs would collapse into one before the guard sees them. GitHub
    keeps them distinct and rejects duplicate keys, so this loader does both too.
    """

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Hashable, Any]:
        mapping = super().construct_mapping(node, deep=deep)
        if len(mapping) != len(node.value):
            raise yaml.constructor.ConstructorError(
                None, None, "found a duplicate key", node.start_mark
            )
        return mapping


def _mappings(node: object) -> Iterator[dict[object, object]]:
    if isinstance(node, dict):
        mapping = cast(dict[object, object], node)
        yield mapping
        for value in mapping.values():
            yield from _mappings(value)
    elif isinstance(node, list):
        for value in cast(list[object], node):
            yield from _mappings(value)


def _names_setup_node(uses: str) -> bool:
    """Whether the runner could resolve `uses` to the actions/setup-node repository."""
    parts = [part.strip().casefold() for part in uses.split("@", 1)[0].split("/")]
    return [part for part in parts if part][:2] == ["actions", "setup-node"]


def setup_node_steps(workflow: str) -> list[dict[object, object]]:
    """Return every setup-node step, raising on a spelling outside the repository's form."""
    steps: list[dict[object, object]] = []
    for mapping in _mappings(yaml.load(workflow, Loader=WorkflowLoader)):
        for key in mapping:
            if EXPRESSION in str(key):
                raise ValueError(f"expression in a mapping key: {key!r}")
        uses = mapping.get("uses")
        if not isinstance(uses, str):
            continue
        if EXPRESSION in uses:
            raise ValueError(f"expression in `uses`: {uses!r}")
        if _names_setup_node(uses):
            if not SETUP_NODE.fullmatch(uses):
                raise ValueError(f"write `actions/setup-node@<commit SHA>`, not {uses!r}")
            steps.append(mapping)
    return steps


def reads_nvmrc(step: dict[object, object]) -> bool:
    """Whether the step's inputs, in their declared spelling, make setup-node read `.nvmrc`."""
    inputs = step.get("with")
    if not isinstance(inputs, dict):
        return False
    given = cast(dict[object, object], inputs)
    if not all(isinstance(name, str) and INPUT_NAME.fullmatch(name) for name in given):
        return False
    return given.get("node-version-file") == ".nvmrc" and "node-version" not in given


def test_nvmrc_names_the_checks_image_node() -> None:
    dockerfile = (ROOT / "ci/checks.Dockerfile").read_text(encoding="utf-8")
    nvmrc = (ROOT / ".nvmrc").read_text(encoding="utf-8")
    assert nvmrc == f"{runtime_node_version(dockerfile)}\n"


def test_workflows_install_node_from_nvmrc() -> None:
    steps = 0
    for workflow in workflow_files(ROOT / ".github/workflows"):
        for step in setup_node_steps(workflow.read_text(encoding="utf-8")):
            assert reads_nvmrc(step), f"{workflow.name}: {step}"
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


def pinned(text: str) -> str:
    """Replace the placeholder ref `@abc` with a full commit SHA."""
    return text.replace("@abc", f"@{'0' * 40}")


def workflow(step: str) -> str:
    steps = textwrap.indent(textwrap.dedent(step).strip("\n"), " " * 6)
    return pinned(f"jobs:\n  checks:\n    steps:\n      - uses: actions/checkout@abc\n{steps}\n")


STEP_CASES = {
    "unquoted": (
        True,
        """
        - uses: actions/setup-node@abc # v7.1.0
          with:
            node-version-file: .nvmrc # the file CI shares
            package-manager-cache: false
        """,
    ),
    "quoted": (
        True,
        """
        - uses: "actions/setup-node@abc"
          with:
            "node-version-file": '.nvmrc'
        """,
    ),
    "flow style": (True, "- {uses: actions/setup-node@abc, with: {node-version-file: .nvmrc}}"),
    "expression value": (
        True,
        """
        - uses: actions/setup-node@abc
          with:
            node-version-file: .nvmrc
            package-manager-cache: ${{ matrix.cache }}
        """,
    ),
    "commented": (
        False,
        """
        - uses: actions/setup-node@abc
          with:
            # node-version-file: .nvmrc
            package-manager-cache: false
        """,
    ),
    "missing": (False, "- uses: actions/setup-node@abc"),
    "other file": (
        False,
        """
        - uses: actions/setup-node@abc
          with:
            node-version-file: .nvmrc-old
        """,
    ),
    "continued value": (
        False,
        """
        - uses: actions/setup-node@abc
          with:
            node-version-file: .nvmrc
              -old
        """,
    ),
    "fixed version": (
        False,
        """
        - uses: actions/setup-node@abc
          with:
            node-version: "24.21.0"
        """,
    ),
    "quoted override": (
        False,
        """
        - uses: actions/setup-node@abc
          with:
            node-version-file: .nvmrc
            'node-version': 22
        """,
    ),
    "escaped override": (
        False,
        """
        - uses: actions/setup-node@abc
          with:
            node-version-file: .nvmrc
            "node\\u002dversion": 22
        """,
    ),
    "inputs as text": (
        False,
        """
        - uses: actions/setup-node@abc
          with: |
            node-version-file: .nvmrc
        """,
    ),
    "capitalised file input": (
        False,
        """
        - uses: actions/setup-node@abc
          with:
            NODE-VERSION-FILE: .nvmrc
        """,
    ),
    "capitalised override": (
        False,
        """
        - uses: actions/setup-node@abc
          with:
            node-version-file: .nvmrc
            NODE-VERSION: 22
        """,
    ),
    "non-ASCII file input": (
        False,
        """
        - uses: actions/setup-node@abc
          with:
            node-verſion-file: .nvmrc
        """,
    ),
}


@pytest.mark.parametrize(("accepted", "step"), STEP_CASES.values(), ids=STEP_CASES.keys())
def test_setup_node_steps_must_read_nvmrc(accepted: bool, step: str) -> None:
    [found] = setup_node_steps(workflow(step))
    assert reads_nvmrc(found) is accepted


REFUSED_STEPS = {
    "capitalised action": "- {uses: Actions/Setup-Node@abc, with: {node-version: 22}}",
    "trailing slash": "- {uses: actions/setup-node/@abc, with: {node-version: 22}}",
    "leading slash": "- {uses: /actions/setup-node@abc, with: {node-version: 22}}",
    "tag instead of SHA": "- {uses: actions/setup-node@v7, with: {node-version-file: .nvmrc}}",
    "expression reference": """
        - uses: ${{ 'actions/setup-node@abc' }}
          with:
            node-version: 22
        """,
    "expression uses key": """
        - "${{ 'uses' }}": actions/setup-node@abc
          with:
            node-version: 22
        """,
    "expression input key": """
        - uses: actions/setup-node@abc
          with:
            node-version-file: .nvmrc
            "${{ 'node-version' }}": 22
        """,
}


@pytest.mark.parametrize("step", REFUSED_STEPS.values(), ids=REFUSED_STEPS.keys())
def test_setup_node_steps_refuse_other_spellings(step: str) -> None:
    with pytest.raises(ValueError):
        setup_node_steps(workflow(step))


def test_yaml_1_1_keywords_stay_distinct_job_ids() -> None:
    steps = setup_node_steps(
        pinned(
            textwrap.dedent(
                """
                on: push
                jobs:
                  yes:
                    steps:
                      - {uses: actions/setup-node@abc, with: {node-version: 22}}
                  on:
                    steps:
                      - {uses: actions/setup-node@abc, with: {node-version-file: .nvmrc}}
                """
            )
        )
    )
    assert [reads_nvmrc(step) for step in steps] == [False, True]


def test_setup_node_steps_refuse_duplicate_keys() -> None:
    with pytest.raises(yaml.constructor.ConstructorError, match="duplicate key"):
        setup_node_steps(
            workflow(
                """
                - uses: actions/setup-node@abc
                  with:
                    node-version: 22
                    node-version: 24
                """
            )
        )


def test_setup_node_steps_ignore_other_steps_and_comments() -> None:
    assert setup_node_steps(workflow("# - uses: actions/setup-node@abc\n- run: echo")) == []

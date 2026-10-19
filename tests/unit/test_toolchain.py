"""Keep the Node that contributors and CI install equal to the checks image's Node."""

import re

from tools.build import ROOT


def test_nvmrc_names_the_checks_image_node() -> None:
    dockerfile = (ROOT / "ci/checks.Dockerfile").read_text(encoding="utf-8")
    image = re.search(r"^FROM node:(\d+\.\d+\.\d+)-", dockerfile, re.MULTILINE)
    assert image is not None
    assert (ROOT / ".nvmrc").read_text(encoding="utf-8") == f"{image[1]}\n"


def test_workflows_install_node_from_nvmrc() -> None:
    workflows = sorted((ROOT / ".github/workflows").glob("*.yml"))
    steps = 0
    for workflow in workflows:
        text = workflow.read_text(encoding="utf-8")
        assert "node-version:" not in text, workflow.name
        uses = text.count("actions/setup-node@")
        assert uses == text.count("node-version-file: .nvmrc"), workflow.name
        steps += uses
    assert steps > 0

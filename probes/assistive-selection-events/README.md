# Probe for #294: selection events of the sheet list's tree

Measurement only, on the research branch `measure-assistive-selection-events`; nothing here is
shipped or merged. It measures, with real input in the Linux Docker lab, which events the sheet
list's tree delivers for a selection made through `XAccessibleSelection`, for a native Ctrl+click
and Ctrl+Shift+click, and for the list's own selection writes, on which thread, whether the solar
mutex is held, and in what order relative to the press's queued mouse listener and the list's
posted work.

- `a11y_probe.py` runs inside soffice, installed into the private profile's user scripts. It
  listens to the tree's accessible context (the one the list listens to for the cursor), to each
  row's context and to the toolkit's `XSelectionChangeListener`, and wraps the live
  `SheetList`'s methods and posting to record when they run. Its module docstring describes the
  records.
- `runner.py` runs with the image's LibreOffice Python. It opens a synthetic workbook of eight
  sheets, Alfa to Hotel, with the repository's UI fixture and runs each phase once per VCL plugin.
- `session.sh` is the container entry point, as `ci/linux-session.sh` and
  `ci/desktop-session.sh` are for the UI suite.
- `summarize.py` prints the records as timelines, with the host's Python.

## Run it

From the repository root, with the package built from the revision under test and the lane's CI
image (as `tools/linux_integration.py current-26.8 --ui` builds it), holding a LibreOffice slot on
a shared machine:

```sh
python tools/build.py
docker run --rm --init --network none --shm-size 512m \
  --env HOME=/tmp/sheet-manager-home \
  --mount "type=bind,source=$PWD,target=/work,readonly" \
  --mount "type=bind,source=$PWD/dist/sheet-manager-0.0.10.oxt,target=/packages/extension.oxt,readonly" \
  --mount "type=bind,source=$PWD/test-results/probe-294,target=/results" \
  --entrypoint /bin/bash sheet-manager-ci:26.8.2.2-11fd8257e0074275 \
  /work/probes/assistive-selection-events/session.sh --vcl gtk3 --vcl gen
python probes/assistive-selection-events/summarize.py test-results/probe-294 [phase ...]
```

`test-results/probe-294/probe-<vcl>/probe-results.json` holds every phase's records.

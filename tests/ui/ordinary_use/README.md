# Ordinary-use walk (research)

Research tooling, not part of `main` or of any required check. It measures ordinary use of the sheet
list at human speed: a seeded random walk of real XTEST input in the Linux Docker lab, compared after
each step with a plain model of what the gestures mean. Whether and how to keep it in the repository
is tracked in #361; until then this branch only preserves it.

- `walk.py` is the walk. It reuses `tests/ui/lab.py`, `workbook.py` and `xinput.py`, observes only
  public UNO, and writes every step as a JSON line to `steps.jsonl`. `--replay FILE` repeats logged
  inputs.
- `model.py` is `Gestures` from `tests/unit/test_input_sequences.py`, tracking sheets by name and
  extended with moves, Undo of the list's own move, double clicks, the wheel and renames.
- `probe_drag.py` is the probe behind #359: a quick short drag of a large pick.
- `run.sh` and `probe-run.sh` start one container of the lab image, wait for 4 GiB of free memory,
  and refuse to start beside another `sm-walk-*` container. `session.sh`, `desktop.sh` and
  `probe-*.sh` run inside it, following `ci/linux-session.sh` and `ci/desktop-session.sh`.

## Running it

Build the image from `ci/Dockerfile` as the Linux Docker lab does; the scripts name it
`sheet-manager-lab:26.8.3.1`. Build the package with `python tools/build.py --output DIR`, then:

```sh
tests/ui/ordinary_use/run.sh run1-gtk3-60-s71 DIR/sheet-manager-VERSION.oxt \
    --vcl gtk3 --sheets 60 --seed 71 --steps 200
```

Results go to `test-results/ordinary-use/NAME/`, or under `$LAB` if it is set. Choose the seeds
before the runs, report every run, and never change a seed or drop a step to make a run pass.

## Coverage

Plain, Ctrl, Shift and Ctrl+Shift clicks on the names and in the gutter; clicks below the rows;
double, right (then Esc) and middle clicks; Up and Down with each modifier, Home, Shift+End,
Ctrl+Space and Ctrl+A; drags of a picked row dropped on itself, up to 8 rows away, or cancelled with
Esc; the move buttons and Alt+Up, Down, Home and End; Ctrl+Z after a list move; renames through the
document API; the wheel.

Not covered: Redo, Enter, type-ahead, Page Up and Page Down, menu commands, Rename Sheets, hidden,
protected and scenario sheets, a real second window, autoscroll, drags of unpicked rows, Tab and F6,
Calc's tabs, the scrollbar, input faster than the list settles, Windows, macOS and LibreOffice 26.2.

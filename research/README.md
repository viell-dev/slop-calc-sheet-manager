# Research branch only (never merged)

Native Windows probes for #179 (and earlier #45), run through this branch's copy of the manual
`windows-desktop.yml` dispatch entry point on a GitHub-hosted runner. `resolve_rvas.py` resolves
the runner build's Calc symbols with TDF's symbol server. `mechanism179.py` tests Calc's
`ScInputHandler::DelayTimer` path without Sheet Manager installed: a hidden Calc load followed by a
colour-scheme change, with visible-load and no-change controls. `probe179.py` repeats the #179
upgrade and Help-before-first-Calc sequence and its control, here under CPU contention. Both
attach a non-invasive CDB trace on request; a per-case watchdog stops a stuck case's own
processes. `analyse_dumps.py` prints every dump's stacks on the runner and deletes the dump, so no
raw dump is uploaded.

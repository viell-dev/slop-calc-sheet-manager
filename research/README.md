# Research branch only (never merged)

Native Windows probes for #179 and #45, run through this branch's copy of the manual
`windows-desktop.yml` dispatch entry point on a GitHub-hosted runner. `resolve_rvas.py` resolves
the runner build's Calc symbols with TDF's symbol server; `probe179.py` repeats the #179 upgrade
and Help-before-first-Calc sequence and its controls with a non-invasive CDB trace; the workflow
then runs the unchanged Windows integration suite. `analyse_dumps.py` prints every dump's stacks
on the runner and deletes the dump, so no raw dump is uploaded.

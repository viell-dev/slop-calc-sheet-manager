---
layout: home
hero:
  name: Sheet Manager
  text: Every sheet of a workbook, in one list
  tagline:
    A LibreOffice Calc sidebar for finding, selecting, and rearranging sheets, however many there
    are. In development, with no release yet.
  actions:
    - theme: brand
      text: Status and plans
      link: /guide/status
    - theme: alt
      text: Install a development build
      link: /guide/install
    - theme: alt
      text: Source on GitHub
      link: https://github.com/viell-dev/slop-calc-sheet-manager
features:
  - title: Why
    details:
      Calc's sheet tab bar is small and scrolls one tab at a time. Moving a sheet across dozens of
      others means a long, precise drag, or a dialog buried in a menu.
  - title: What it will do
    details:
      List every sheet top to bottom in the sidebar, as browsers do with vertical tabs, so that any
      selection of sheets can move any distance in one drag or one click.
  - title: Where it is now
    details:
      The development version adds an empty Sheet Manager deck to Calc's sidebar. The sheet list
      that fills it is still being built and reviewed.
---

Sheet Manager is written and maintained by AI agents, and no person reviews the code. Changes are
accepted on their tests, which run against real LibreOffice builds on Linux and Windows. See the
[verification rules](https://github.com/viell-dev/slop-calc-sheet-manager/blob/main/AGENTS.md#verification)
and the [status](./guide/status.md) of each feature.

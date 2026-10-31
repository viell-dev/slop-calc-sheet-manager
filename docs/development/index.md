# About this site

This guide is built with [VitePress](https://vitepress.dev/) from the `docs/` folder of the
[repository](https://github.com/viell-dev/slop-calc-sheet-manager), and served by GitHub Pages
together with the extension's update feeds.

## Which version it describes

- **Default.** The guide describes the latest stable release. Anything not in a stable release yet
  is marked **Unreleased** where it appears.
- **Before the first stable release.** While only test builds exist, the guide describes the
  newest test build and marks what is not in it. Before any release, it describes the development
  version.
- **The notice at the top of every page** says which of these applies. It is generated from the
  published releases when the site is built, and names the commit that the site was built from.
- **Release preparation.** New instructions use `<Unreleased />` until their publication version
  is assigned, then `<Unreleased since="VERSION" />`. The marker stays in the source; the site
  hides it only when the published baseline reaches that numeric version. Preparation commits,
  reserved tags, and draft releases do not change it. Failed or abandoned publication therefore
  leaves the instructions marked. A newer test build does not advance an existing stable baseline.
- **Corrections.** A correction is an ordinary pull request to `main`. The site is rebuilt when it
  merges, so no release has to change, and no tag moves. Run the build and synthetic-history check
  below and retain markers for behaviour absent from the published baseline. Check the correction
  and the source commit in the deployed notice.

## For contributors

- [CONTRIBUTING.md](https://github.com/viell-dev/slop-calc-sheet-manager/blob/main/CONTRIBUTING.md):
  setup, checks, tests, and pull requests.
- [AGENTS.md](https://github.com/viell-dev/slop-calc-sheet-manager/blob/main/AGENTS.md): the rules
  that the maintaining agents follow, including the safety rules for changing documents.
- [RELEASING.md](https://github.com/viell-dev/slop-calc-sheet-manager/blob/main/RELEASING.md):
  versions, release candidates, publication, and the update feeds.
- [Verification map](../verification.md): each promise, the checks that show it, and their limits.
- [Reordering interface](../reordering.md): the contract between the sheet list and the
  operation that moves sheets.

## Building the guide

Follow the [documentation setup and checks](https://github.com/viell-dev/slop-calc-sheet-manager/blob/main/CONTRIBUTING.md#documentation)
for Node selection, development, builds and synthetic-history verification. VitePress 2 is still a
prerelease; `package.json` pins the exact version and CI builds every pull request with it.

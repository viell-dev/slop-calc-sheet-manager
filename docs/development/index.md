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
- **Corrections.** A correction is an ordinary pull request to `main`. The site is rebuilt when it
  merges, so no release has to change, and no tag moves.

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

The guide's tools are its only Node.js dependencies. Use the Node.js version in `.nvmrc`; `nvm use`
or `fnm use` in the repository selects it. Then run:

```sh
npm ci
npm run docs:dev
```

`npm run docs:build` builds the site as CI does, and fails on a broken link between pages.
After installing the Node dependencies, `python tools/check_release_page.py` checks the rendered
release page with empty and synthetic histories, including channel separation and asset links.
Its temporary outputs stay under `test-results/`; it makes no publication changes.

VitePress 2 is still a prerelease. The repository pins an exact version, and every pull request
builds the site with it.

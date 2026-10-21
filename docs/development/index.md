# About this site

This guide is built with [VitePress](https://vitepress.dev/) from the `docs/` folder of the
[repository](https://github.com/viell-dev/slop-calc-sheet-manager), and served by GitHub Pages
together with the extension's update feeds.

## Which version it describes

- **Default.** The guide describes the latest release. Anything that exists only in the
  development version on `main` is marked **Unreleased** where it appears.
- **Before the first release.** There is no release yet, so the whole guide describes the
  development version and says so at the top of every page.
- **The notice at the top** is generated from the published releases when the site is built.
- **The footer** names the commit that the site was built from.
- **Corrections.** A correction is an ordinary pull request to `main`. The site is rebuilt when it
  merges, so no release has to change, and no tag moves.

## For contributors

- [CONTRIBUTING.md](https://github.com/viell-dev/slop-calc-sheet-manager/blob/main/CONTRIBUTING.md):
  setup, checks, tests, and pull requests.
- [AGENTS.md](https://github.com/viell-dev/slop-calc-sheet-manager/blob/main/AGENTS.md): the rules
  that the maintaining agents follow, including the safety rules for changing documents.
- [RELEASING.md](https://github.com/viell-dev/slop-calc-sheet-manager/blob/main/RELEASING.md):
  versions, release candidates, publication, and the update feeds.
- [Reordering interface](../reordering.md): the contract between the planned sheet list and the
  operation that moves sheets.

## Building the guide

The guide's tools are its only Node.js dependencies. Use the Node.js version in `.nvmrc`; `nvm use`
or `fnm use` in the repository selects it. Then run:

```sh
npm ci
npm run docs:dev
```

`npm run docs:build` builds the site as CI does, and fails on a broken link between pages.

VitePress 2 is still a prerelease. The repository pins an exact version, and every pull request
builds the site with it.

<script setup>
import ReleaseDownloads from "../.vitepress/theme/ReleaseDownloads.vue";
</script>

# Releases and test builds

Every published build has a [GitHub release](https://github.com/viell-dev/slop-calc-sheet-manager/releases)
with release notes, an `.oxt` manual-install package, and its `.oxt.sha256` checksum. This includes
test builds marked **Pre-release**, as well as stable releases. GitHub's automatic source
archives are for developers; install the OXT asset in LibreOffice.

## Stable releases

Use a stable release for ordinary work. LibreOffice's **Check for Updates** offers newer stable
versions that meet its compatibility requirements. See [Install, update, and remove](./install.md)
for installation and checksum instructions.

<ReleaseDownloads :prerelease="false" />

## Test builds

Test builds are for trying changes before a stable release. Download and install their OXT
packages manually. Installing one keeps the stable update feed: it will offer a newer final
release, but does not offer later test builds. An extension-directory listing is not needed to
install these GitHub assets.

<ReleaseDownloads :prerelease="true" />

## Version numbers

Sheet Manager uses three numeric components, but **does not use full Semantic Versioning**.
LibreOffice compares the installed extension's version itself. It considers `0.1.0-beta.1` and
`0.1.0-rc.1` newer than `0.1.0`, whereas SemVer places them below it. The final release would not
be offered as an update to those test builds; manually installing it would be shown as a downgrade.
This is a host-application constraint, independent of GitHub and the extension directory.

We keep the same version in the OXT, Git tag, release and asset names. Test builds use increasing
numbers below the final release, reserving patch numbers from `.90` in the preceding series.
For example:

| GitHub release title | OXT version and Git tag | Build type |
| --- | --- | --- |
| 0.1.0 release candidate 1 (0.0.90) | `0.0.90` | Pre-release |
| 0.1.0 release candidate 2 (0.0.91) | `0.0.91` | Pre-release |
| 0.1.0 | `0.1.0` | Stable |

These are examples; the download lists above show what is actually published. The `.90` range
is our convention, not a LibreOffice requirement. It reserves high patch numbers for candidates:
after `0.1.90` starts testing `0.2.0`, a lower `0.1.2` would no longer be an upgrade. Stable patch
releases therefore stay below `.90`, and entering the candidate range waits until that stable
series needs no further fixes. Before 1.0, feature releases may change compatibility.

Using SemVer tags with different numeric versions inside the OXT is possible, but would require
a separate mapping and leave two version numbers to identify the same build. We keep one version
instead. [The maintainer policy](https://github.com/viell-dev/slop-calc-sheet-manager/blob/main/RELEASING.md#versions-and-titles)
links the native comparison code and defines numbering, validation and recovery.

## Machine update feeds

The [stable XML feed](https://viell-dev.github.io/slop-calc-sheet-manager/updates/stable.xml) is
for LibreOffice's update mechanism. The
[all-builds XML feed](https://viell-dev.github.io/slop-calc-sheet-manager/updates/prerelease.xml)
also contains test builds. These are machine-readable metadata; use the download lists above
or GitHub Releases to choose and install a package.

import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { type DefaultTheme, defineConfigWithTheme } from "vitepress";

const repository = "https://github.com/viell-dev/slop-calc-sheet-manager";

// The Pages workflow sets SHEET_MANAGER_RELEASES to the release history it generated from the
// published GitHub releases. Without it, as in pull request builds, the site says that it
// describes the development version, which is all there is until the first release.
export interface PublishedBuild {
  version: string;
  prerelease: boolean;
  minimum: string;
  published: string;
}

function releases(): PublishedBuild[] {
  const path = process.env.SHEET_MANAGER_RELEASES;
  if (!path || !existsSync(path)) {
    return [];
  }
  return JSON.parse(readFileSync(path, "utf8")) as PublishedBuild[];
}

function newest(builds: PublishedBuild[], prerelease: boolean): PublishedBuild | null {
  const order = (build: PublishedBuild) => build.version.split(".").map(Number);
  const candidates = builds.filter((build) => build.prerelease === prerelease);
  candidates.sort((a, b) => {
    const [x, y] = [order(a), order(b)];
    for (let index = 0; index < Math.max(x.length, y.length); index += 1) {
      const difference = (y[index] ?? 0) - (x[index] ?? 0);
      if (difference !== 0) {
        return difference;
      }
    }
    return 0;
  });
  return candidates[0] ?? null;
}

export interface ThemeConfig extends DefaultTheme.Config {
  release: { stable: PublishedBuild | null; prerelease: PublishedBuild | null };
}

// The commit the site is built from, for its footer: from Git, or SHEET_MANAGER_DOCS_COMMIT where
// Git is unavailable, as in a container without it.
function sourceCommit(): string {
  try {
    return execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim();
  } catch {
    return process.env.SHEET_MANAGER_DOCS_COMMIT ?? "unknown";
  }
}

const builds = releases();
const commit = sourceCommit();

export default defineConfigWithTheme<ThemeConfig>({
  title: "Sheet Manager",
  description:
    "A LibreOffice Calc sidebar that lists a workbook's sheets top to bottom. In development.",
  base: "/slop-calc-sheet-manager/",
  lang: "en",
  cleanUrls: true,
  lastUpdated: false,
  themeConfig: {
    release: {
      stable: newest(builds, false),
      prerelease: newest(builds, true),
    },
    nav: [
      { text: "Guide", link: "/guide/status" },
      { text: "Development", link: "/development/" },
      { text: "Releases", link: `${repository}/releases` },
    ],
    sidebar: [
      {
        text: "Guide",
        items: [
          { text: "Status and plans", link: "/guide/status" },
          { text: "Install, update, and remove", link: "/guide/install" },
          { text: "Use the deck", link: "/guide/use" },
          { text: "Compatibility and known issues", link: "/guide/known-issues" },
          { text: "Troubleshooting", link: "/guide/troubleshooting" },
          { text: "Report a problem", link: "/guide/report" },
        ],
      },
      {
        text: "Development",
        items: [
          { text: "About this site", link: "/development/" },
          { text: "Reordering interface", link: "/reordering" },
        ],
      },
    ],
    socialLinks: [{ icon: "github", link: repository }],
    editLink: {
      pattern: `${repository}/edit/main/docs/:path`,
      text: "Suggest a change to this page",
    },
    footer: {
      message: `Built from <a href="${repository}/commit/${commit}">${commit.slice(0, 7)}</a> on main. Released under the <a href="${repository}/blob/main/LICENSE">Mozilla Public License 2.0</a>.`,
      copyright: "Written and maintained by AI agents.",
    },
    search: { provider: "local" },
  },
});

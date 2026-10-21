<script setup lang="ts">
import { useData, withBase } from "vitepress";
import type { ThemeConfig } from "../config.mts";

// Computed at build time from the published releases and the source commit; see config.mts.
const { theme } = useData<ThemeConfig>();
const { release, commit, repository } = theme.value;
</script>

<template>
  <div class="release-notice" role="note">
    <template v-if="release.stable">
      This guide describes Sheet Manager {{ release.stable.version }}, the latest release. Parts
      marked <strong>Unreleased</strong> are not in a stable release yet.
    </template>
    <template v-else-if="release.prerelease">
      Sheet Manager has no stable release yet. This guide describes
      {{ release.prerelease.version }}, the newest test build; parts marked
      <strong>Unreleased</strong> are not in it yet.
    </template>
    <template v-else>
      Sheet Manager has no release yet. This guide describes the development version; see
      <a :href="withBase('/guide/status')">Status and plans</a>.
    </template>
    <span class="release-notice-commit">
      Built from
      <a v-if="commit !== 'unknown'" :href="`${repository}/commit/${commit}`">{{
        commit.slice(0, 7)
      }}</a>
      <template v-else>an unknown commit</template>.
    </span>
  </div>
</template>

<style scoped>
.release-notice {
  margin: 0 auto 24px;
  max-width: 1152px;
  padding: 12px 16px;
  border-radius: 8px;
  font-size: 14px;
  line-height: 1.5;
  color: var(--vp-c-text-1);
  background-color: var(--vp-c-warning-soft);
}

.release-notice-commit {
  color: var(--vp-c-text-2);
}
</style>

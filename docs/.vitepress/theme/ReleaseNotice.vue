<script setup lang="ts">
import { useData } from "vitepress";
import type { ThemeConfig } from "../config.mts";

// Computed at build time from the published releases; see config.mts.
const { theme } = useData<ThemeConfig>();
const release = theme.value.release;
</script>

<template>
  <div class="release-notice" role="note">
    <template v-if="release.stable">
      This guide describes Sheet Manager {{ release.stable.version }}, the latest release. Parts
      marked <strong>Unreleased</strong> describe the development version.
    </template>
    <template v-else-if="release.prerelease">
      Sheet Manager has no stable release yet; the newest test build is
      {{ release.prerelease.version }}. This guide describes the development version.
    </template>
    <template v-else>
      Sheet Manager has no release yet. This guide describes the development version, which adds
      an empty deck to Calc's sidebar; the sheet list is still being built.
    </template>
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
</style>

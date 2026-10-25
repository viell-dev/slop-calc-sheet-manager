<script setup lang="ts">
import { useData } from "vitepress";
import type { ThemeConfig } from "../config.mts";

const props = defineProps<{ prerelease: boolean }>();
const { theme } = useData<ThemeConfig>();
const { release, repository } = theme.value;
const builds = release.builds.filter((build) => build.prerelease === props.prerelease);
const packageName = (version: string) => `sheet-manager-${version}.oxt`;
const download = (version: string) => `${repository}/releases/download/${version}/${packageName(version)}`;
</script>

<template>
  <p v-if="builds.length === 0">
    No {{ prerelease ? "test builds" : "stable releases" }} have been published yet.
  </p>
  <table v-else>
    <thead>
      <tr>
        <th scope="col">Version and release notes</th>
        <th scope="col">LibreOffice minimum</th>
        <th scope="col">Manual install</th>
      </tr>
    </thead>
    <tbody>
      <tr v-for="build in builds" :key="build.version">
        <td><a :href="`${repository}/releases/tag/${build.version}`">{{ build.version }}</a></td>
        <td>{{ build.minimum }}</td>
        <td>
          <a :href="download(build.version)">OXT package</a> ·
          <a :href="`${download(build.version)}.sha256`">SHA-256 checksum</a>
        </td>
      </tr>
    </tbody>
  </table>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useData } from "vitepress";
import type { ThemeConfig } from "../config.mts";

const props = defineProps<{ since?: string }>();
if (props.since !== undefined && !/^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.test(props.since)) {
  throw new Error(`Unreleased since must be a plain numeric version: ${props.since}`);
}
const { theme } = useData<ThemeConfig>();
const unreleased = computed(() => {
  const baseline = theme.value.release.stable ?? theme.value.release.prerelease;
  if (!props.since || !baseline) {
    return true;
  }
  const published = baseline.version.split(".").map(Number);
  const difference = props.since.split(".").map((part, index) => Number(part) - published[index]);
  return (difference.find((part) => part !== 0) ?? 0) > 0;
});
</script>

<template>
  <span v-if="unreleased" class="unreleased" :data-since="since ?? 'pending'">
    <strong>Unreleased</strong><template v-if="since"> (requires {{ since }})</template>:
  </span>
</template>

import DefaultTheme from "vitepress/theme";
import { h } from "vue";
import ReleaseNotice from "./ReleaseNotice.vue";

// The notice sits at the top of every page's content, so it never covers the fixed navigation.
export default {
  extends: DefaultTheme,
  Layout: () =>
    h(DefaultTheme.Layout, null, {
      "home-hero-before": () => h(ReleaseNotice),
      "doc-before": () => h(ReleaseNotice),
    }),
};

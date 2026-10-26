import DefaultTheme from "vitepress/theme";
import { type App, h } from "vue";
import ReleaseNotice from "./ReleaseNotice.vue";
import Unreleased from "./Unreleased.vue";

// The notice sits at the top of every page's content, so it never covers the fixed navigation.
export default {
  extends: DefaultTheme,
  enhanceApp({ app }: { app: App }) {
    app.component("Unreleased", Unreleased);
  },
  Layout: () =>
    h(DefaultTheme.Layout, null, {
      "home-hero-before": () => h(ReleaseNotice),
      "doc-before": () => h(ReleaseNotice),
    }),
};

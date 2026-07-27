// Stylesheet order matters: tokens define the custom properties base.css and every
// scoped component style consume, so it must load first. There is deliberately no
// global class stylesheet — the prototype's was retired in P4-07.
import "@xterm/xterm/css/xterm.css";
import "./theme/tokens.css";
import "./theme/base.css";
import { createApp } from "vue";
import { createPinia } from "pinia";
import App from "./App.vue";
import { createAppRouter } from "./router";

const app = createApp(App);
app.use(createPinia());
app.use(createAppRouter());
app.mount("#app");

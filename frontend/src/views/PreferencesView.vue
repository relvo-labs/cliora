<script setup lang="ts">
// Personal settings. Every display preference in one place.
//
// The theme control started life as a bare `<select>` in the header, which was
// wrong twice over. It made a global preference look like a per-page control,
// and it left the other three preferences with no home at all — the terminal
// font size was reachable only from the session workspace, and the nav collapse
// and file-panel width only by manipulating the thing itself. plan/28's own
// §4 had already said the account menu should carry this; it just was not built.
//
// This is deliberately **not** `/settings/integrations`' neighbour in meaning.
// That page is platform configuration and needs `integration.manage`. This one
// needs no permission at all, because nothing here is a capability: every value
// is a display preference stored in this browser, and none of them is sent to
// the server or read as authorization (`NFR-006.AC-07`).
//
// The honest cost is stated on the page rather than in a release note nobody
// re-reads: **these do not follow you to another machine.**

import { computed } from "vue";
import { Monitor, MoonStar, Sun } from "lucide-vue-next";

import AppLayout from "../components/layout/AppLayout.vue";
import UiButton from "../components/ui/UiButton.vue";
import UiField from "../components/ui/UiField.vue";
import UiInlineNotice from "../components/ui/UiInlineNotice.vue";
import {
  INSPECTOR_DEFAULT,
  INSPECTOR_MAX,
  INSPECTOR_MIN,
  TERMINAL_FONT_DEFAULT,
  TERMINAL_FONT_MAX,
  TERMINAL_FONT_MIN,
  usePreferencesStore,
} from "../stores/preferences";
import { SHIPPED_THEME_IDS, type ShippedThemeId } from "../theme/themes";
import { prefersLight } from "../theme/applyTheme";

const preferences = usePreferencesStore();

// Three options, not two. "Follow the system" is a real state that the previous
// two-option select could not express, so a user who had ever picked a theme
// could never hand the decision back to their OS.
const THEMES: Array<{
  id: ShippedThemeId;
  label: string;
  detail: string;
  icon: typeof Sun;
}> = [
  {
    id: "graphite",
    label: "石墨（深色）",
    detail:
      "預設。終端與唯讀預覽本來就是深色，深色外框不會在你盯著的那一塊周圍畫出一道高對比邊界。",
    icon: MoonStar,
  },
  {
    id: "porcelain",
    label: "明亮（淺色）",
    detail:
      "白底鈷藍。終端與程式預覽仍然是深色——淺色外框裡的深色終端有它自己的一套文字色。",
    icon: Sun,
  },
];

// The list above is hand-written because each option carries its own
// explanation, which a generated list cannot. That makes it something that can
// drift from the shipped set, so it is checked here rather than left to a
// reviewer noticing: adding a third shipped theme without giving it a
// description and a reason must fail loudly, not render two radios and hide the
// new one.
if (import.meta.env.DEV && THEMES.length !== SHIPPED_THEME_IDS.length) {
  throw new Error(
    `PreferencesView lists ${THEMES.length} themes but ${SHIPPED_THEME_IDS.length} ship: ` +
      `${SHIPPED_THEME_IDS.join(", ")}. Every shipped theme needs an option here.`,
  );
}

// What the OS currently says, so "follow the system" can show what that means
// right now instead of leaving the user to guess.
const systemLabel = computed(() => (prefersLight() ? "淺色" : "深色"));
// Reads the store rather than the media query, so it says what is actually
// painted right now and follows a rotation without this view knowing how.
const pocketInForce = computed(
  () => preferences.renderedTheme !== preferences.theme,
);
</script>

<template>
  <AppLayout>
    <div class="page">
      <header class="head">
        <h1>個人設定</h1>
        <p>只影響這個瀏覽器的顯示方式，不改變任何權限。</p>
      </header>

      <!-- Stated on the page, not only in the release note: this is the one
           thing about these settings that will surprise someone. -->
      <UiInlineNotice
        tone="info"
        title="這些設定存在這個瀏覽器裡"
        message="換一台機器或換一個瀏覽器，設定不會跟著走。目前沒有跨裝置同步——視覺偏好沒有理由動到你的帳號資料。"
      />

      <section class="group">
        <div class="group-head">
          <h2>視覺主題</h2>
          <p>
            頁面、終端與唯讀預覽共用同一份色彩來源，所以換主題時三者會一起換。
            切換不會中斷 Session，也不會重建終端。
          </p>
        </div>

        <!-- Without this the switcher and the screen contradict each other in
             public: the radio still shows the user's choice, and the page is
             painted in something else entirely. Saying so is cheaper than
             making the control lie (plan/29 MS-20). -->
        <UiInlineNotice v-if="pocketInForce" tone="info">
          這個裝置的視窗寬度固定使用行動明亮配色，下面的選擇會被保留，
          但要在較寬的視窗才會生效。
        </UiInlineNotice>

        <fieldset class="choices">
          <legend class="sr-only">視覺主題</legend>

          <!-- The system option first: it is the default state, and putting it
               last would read as an afterthought. -->
          <label
            class="choice"
            :data-selected="!preferences.themeIsExplicit || undefined"
          >
            <input
              type="radio"
              name="theme"
              :checked="!preferences.themeIsExplicit"
              @change="preferences.followSystemTheme()"
            />
            <Monitor class="icon" aria-hidden="true" />
            <span class="body">
              <span class="label">跟隨系統</span>
              <span class="detail">
                依作業系統的淺色／深色偏好決定。你的系統目前是<strong>{{
                  systemLabel
                }}</strong
                >。
              </span>
            </span>
          </label>

          <label
            v-for="theme in THEMES"
            :key="theme.id"
            class="choice"
            :data-selected="
              (preferences.themeIsExplicit && preferences.theme === theme.id) ||
              undefined
            "
          >
            <input
              type="radio"
              name="theme"
              :checked="
                preferences.themeIsExplicit && preferences.theme === theme.id
              "
              @change="preferences.setTheme(theme.id)"
            />
            <component :is="theme.icon" class="icon" aria-hidden="true" />
            <span class="body">
              <span class="label">{{ theme.label }}</span>
              <span class="detail">{{ theme.detail }}</span>
            </span>
          </label>
        </fieldset>

        <p class="note">
          設計階段做了五款風格，<strong>經過驗收的是上面兩款</strong>。
          另外三款（午夜藍、暖灰工作室、工業終端）的色值在程式裡、也通過自動色彩檢查，
          但沒有人在瀏覽器裡看過它們，版型差異也沒有實作，所以不提供選擇——
          「支援五種主題」不會是一句真話。
        </p>
      </section>

      <section class="group">
        <div class="group-head">
          <h2>終端</h2>
          <p>
            這不只是舒適度設定。1024×768 的視窗用預設 14px 只有 28 列， 調成
            13px 會回到 30 列。工作台的狀態列也有同一組控制項。
          </p>
        </div>
        <div class="row">
          <UiField
            label="終端字級"
            :hint="`${TERMINAL_FONT_MIN}–${TERMINAL_FONT_MAX} px，預設 ${TERMINAL_FONT_DEFAULT} px。改變後會重新 fit，不會重連。`"
          >
            <template #default="{ id, describedBy }">
              <div class="slider">
                <input
                  :id="id"
                  type="range"
                  :min="TERMINAL_FONT_MIN"
                  :max="TERMINAL_FONT_MAX"
                  :value="preferences.terminalFontSize"
                  :aria-describedby="describedBy"
                  :aria-valuetext="`${preferences.terminalFontSize} px`"
                  @input="
                    preferences.setTerminalFontSize(
                      Number(($event.target as HTMLInputElement).value),
                    )
                  "
                />
                <!-- The value as text, not only as a slider position. -->
                <output class="value"
                  >{{ preferences.terminalFontSize }} px</output
                >
              </div>
            </template>
          </UiField>
        </div>
      </section>

      <section class="group">
        <div class="group-head">
          <h2>版面</h2>
          <p>導覽在 1440px 以下會自動收合，這個設定只影響 1440px 以上。</p>
        </div>
        <div class="row">
          <UiField
            label="檔案欄寬度"
            :hint="`${INSPECTOR_MIN}–${INSPECTOR_MAX} px，預設 ${INSPECTOR_DEFAULT} px。也可以直接拖工作台裡那條分隔線。`"
          >
            <template #default="{ id, describedBy }">
              <div class="slider">
                <input
                  :id="id"
                  type="range"
                  :min="INSPECTOR_MIN"
                  :max="INSPECTOR_MAX"
                  :step="2"
                  :value="preferences.inspectorWidth"
                  :aria-describedby="describedBy"
                  :aria-valuetext="`${preferences.inspectorWidth} px`"
                  @input="
                    preferences.setInspectorWidth(
                      Number(($event.target as HTMLInputElement).value),
                    )
                  "
                />
                <output class="value"
                  >{{ preferences.inspectorWidth }} px</output
                >
              </div>
            </template>
          </UiField>
        </div>
        <label class="toggle">
          <input
            type="checkbox"
            :checked="preferences.navCollapsed"
            @change="
              preferences.setNavCollapsed(
                ($event.target as HTMLInputElement).checked,
              )
            "
          />
          <span>
            <span class="label">導覽保持收合</span>
            <span class="detail">
              收合後只剩圖示，每一項仍然可以 Tab 到、仍然有可讀名稱。
              收合是顯示狀態，不是權限——因為權限不足而隱藏的項目在兩種狀態下都是隱藏的。
            </span>
          </span>
        </label>
      </section>

      <section class="group">
        <div class="group-head">
          <h2>回復預設</h2>
          <p>把這四項都恢復成初始狀態（主題回到跟隨系統）。</p>
        </div>
        <UiButton
          variant="secondary"
          @click="
            preferences.followSystemTheme();
            preferences.setTerminalFontSize(TERMINAL_FONT_DEFAULT);
            preferences.setInspectorWidth(INSPECTOR_DEFAULT);
            preferences.setNavCollapsed(false);
          "
        >
          回復預設設定
        </UiButton>
      </section>
    </div>
  </AppLayout>
</template>

<style scoped>
.page {
  display: grid;
  gap: 26px;
  max-width: 760px;
}
.head h1 {
  margin: 0;
  font-size: 24px;
  letter-spacing: -0.02em;
}
.head p {
  margin: 6px 0 0;
  color: var(--text-secondary);
  font-size: 13px;
}
.group {
  display: grid;
  gap: 14px;
  padding: 20px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-panel);
  background: var(--surface-default);
}
.group-head h2 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
}
.group-head p {
  margin: 6px 0 0;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.7;
  max-width: 68ch;
}
.note {
  margin: 0;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.7;
  max-width: 68ch;
}

fieldset.choices {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 0;
  border: 0;
}
.choice {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 12px 14px;
  /* border-control, not border-subtle: this is a real control boundary. */
  border: 1px solid var(--border-control);
  border-radius: var(--radius-control);
  cursor: pointer;
}
.choice:hover {
  background: var(--surface-raised);
}
/* Four signals, not one: tint, text colour, a 2px edge and weight — the same
   rule the nav's selected state follows. */
.choice[data-selected] {
  background: var(--accent-subtle);
  border-color: var(--accent-primary);
  border-left-width: 2px;
}
.choice[data-selected] .label {
  color: var(--accent-strong);
  font-weight: 650;
}
.choice input[type="radio"] {
  margin-top: 2px;
  accent-color: var(--accent-strong);
}
.choice .icon {
  width: 17px;
  height: 17px;
  margin-top: 1px;
  flex-shrink: 0;
  color: var(--text-secondary);
}
.choice[data-selected] .icon {
  color: var(--accent-strong);
}
.body {
  display: grid;
  gap: 3px;
  min-width: 0;
}
.label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}
.detail {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.6;
}

.row {
  max-width: 420px;
}
.slider {
  display: flex;
  align-items: center;
  gap: 12px;
}
.slider input[type="range"] {
  flex: 1;
  min-width: 0;
  accent-color: var(--accent-strong);
}
.value {
  min-width: 52px;
  text-align: right;
  font-variant-numeric: tabular-nums;
  font-size: 13px;
  color: var(--text-primary);
}

.toggle {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  cursor: pointer;
}
.toggle input {
  margin-top: 2px;
  accent-color: var(--accent-strong);
}
.toggle span {
  display: grid;
  gap: 3px;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}
</style>

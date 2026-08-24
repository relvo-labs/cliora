// The eight attention levels as the console renders them (PX-18, plan/26/03 §2).
//
// **The order is the server's and this file does not rebuild it.** `primary` arrives
// already chosen by `derive_attention`; what lives here is presentation — the label a
// person reads, the token that colours it, and the shape and glyph that carry the same
// meaning when the colour does not arrive. `ATTENTION_LEVELS` exists only so that the
// component test can iterate every level; nothing sorts by it.
//
// **Colour is never the only cue** (research/style.md §22): every entry below has a
// label and a glyph, and `variant` gives the top two levels a solid fill the rest do not
// have. That is three cues where the rule asks for two, and the third is free.

export const ATTENTION_LEVELS = [
  "waiting_for_your_input",
  "pending_human_approval",
  "verification_failed",
  "run_failed",
  "no_eligible_runner",
  "assigned_runner_offline",
  "dependency_blocked",
  "over_wip_or_stale",
] as const;

export type AttentionLevel = (typeof ATTENTION_LEVELS)[number];

export interface AttentionPresentation {
  /** The whole sentence, not a category. "注意" tells a reader nothing to do. */
  label: string;
  /** Shortened for the compact density; still a verb phrase, never an abbreviation. */
  short: string;
  /** A `--attention-*` token name. Five tokens across eight levels: levels cleared by
   *  the same action share a colour (research/style.md §22). */
  tone: string;
  /** Text, so it survives a missing icon font and reads out to a screen reader as part
   *  of the label rather than as a separate node. */
  glyph: string;
  /** Solid for the two levels where a person is actively being waited on, outline for
   *  the rest. The shape difference is the second cue. */
  variant: "solid" | "outline";
}

export const ATTENTION: Record<AttentionLevel, AttentionPresentation> = {
  waiting_for_your_input: {
    label: "等待你的回覆",
    short: "等你回覆",
    tone: "attention-human",
    glyph: "◆",
    variant: "solid",
  },
  pending_human_approval: {
    label: "等待人工核准",
    short: "等待核准",
    tone: "attention-approval",
    glyph: "◆",
    variant: "solid",
  },
  verification_failed: {
    label: "驗證未通過",
    short: "驗證失敗",
    tone: "attention-failed",
    glyph: "✕",
    variant: "outline",
  },
  run_failed: {
    label: "執行失敗",
    short: "執行失敗",
    tone: "attention-failed",
    glyph: "✕",
    variant: "outline",
  },
  no_eligible_runner: {
    label: "沒有符合條件的 Agent",
    short: "無可用 Agent",
    tone: "attention-warning",
    glyph: "▲",
    variant: "outline",
  },
  assigned_runner_offline: {
    label: "指定的 Agent 離線",
    short: "Agent 離線",
    tone: "attention-warning",
    glyph: "▲",
    variant: "outline",
  },
  dependency_blocked: {
    label: "被其他卡片阻塞",
    short: "被阻塞",
    tone: "attention-blocked",
    glyph: "⊘",
    variant: "outline",
  },
  over_wip_or_stale: {
    label: "停滯或超出 WIP",
    short: "停滯",
    tone: "attention-warning",
    glyph: "◷",
    variant: "outline",
  },
};

/** Whether a string off the wire is a level this build knows how to draw.
 *
 *  A ninth level added server-side must not render as a blank badge: an unknown value
 *  is dropped, and the card looks the way it did before the level existed. */
export function isAttentionLevel(value: string): value is AttentionLevel {
  return (ATTENTION_LEVELS as readonly string[]).includes(value);
}

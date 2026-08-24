// The filter builder's vocabulary (PX-31, plan/26/06 §2, plan/26/04 §2–3).
//
// **A subset of the server's fifteen fields, chosen rather than generated.** Every field
// the compiler accepts could be offered here, and three of them should not be: `owner`,
// `assigned_runner`, `epic`, `user_story` and `requirement` take a uuid, so a text box for
// them is a text box nobody can fill in correctly. Those belong to pickers that this phase
// does not build — `plan/26/11` §3 records that as the follow-up — and offering a broken
// control is worse than offering none.
//
// So this file lists the fields whose values are a **closed set**: pick a field, pick an
// operator, pick a value. Nothing to type, nothing to get wrong, and no client-side
// validation that could disagree with the server's.
//
// The builder's output is the **same `f=` a quick-filter chip writes**. A chip is a saved
// row of this, not a second mechanism — which is why toggling a chip lights up when the
// builder happens to have built that filter, and why "clear" has one meaning.

export interface BuilderOption {
  value: string;
  label: string;
}

export interface BuilderField {
  field: string;
  label: string;
  /** The operators offered, in the order they read. */
  ops: readonly ("eq" | "neq" | "in" | "not_in")[];
  options: readonly BuilderOption[];
}

const EQUALITY = ["eq", "neq"] as const;
const ALL_OPS = ["eq", "neq", "in", "not_in"] as const;

/** Eight fields, and each one's values come from the server's own frozensets.
 *
 *  Kept in sync by `GATE-PX-BUILDER-SUBSET`, which parses this file, reads the server's
 *  `FIELDS`, and fails if any `(field, op, value)` triple here is one the compiler would
 *  refuse. It is a gate rather than a unit test because nothing in either language can
 *  notice the two drifting — and the failure that drift produces is a **400 from a
 *  dropdown the person was invited to use**. The gate caught six wrong values the first
 *  time it ran, in three of the eight fields. */
export const BUILDER_FIELDS: readonly BuilderField[] = [
  {
    field: "lifecycle",
    label: "階段",
    ops: ALL_OPS,
    options: [
      { value: "backlog", label: "待辦" },
      { value: "ready", label: "就緒" },
      { value: "in_progress", label: "進行中" },
      { value: "review", label: "驗證中" },
      { value: "done", label: "完成" },
    ],
  },
  {
    field: "attention",
    label: "注意力",
    ops: ALL_OPS,
    options: [
      { value: "waiting_for_your_input", label: "等你回覆" },
      { value: "pending_human_approval", label: "等人核准" },
      { value: "verification_failed", label: "驗證失敗" },
      { value: "run_failed", label: "執行失敗" },
      { value: "dependency_blocked", label: "被相依阻塞" },
      { value: "no_eligible_runner", label: "無可用 Agent" },
      { value: "assigned_runner_offline", label: "指定 Agent 離線" },
      { value: "over_wip_or_stale", label: "超 WIP 或久未更新" },
    ],
  },
  {
    field: "readiness",
    label: "就緒狀態",
    ops: ALL_OPS,
    options: [
      { value: "ready", label: "齊備" },
      { value: "needs_clarification", label: "待釐清" },
      { value: "draft", label: "草稿" },
    ],
  },
  {
    field: "execution_status",
    label: "執行狀態",
    ops: ALL_OPS,
    options: [
      { value: "not_queued", label: "未派工" },
      { value: "queued", label: "排隊中" },
      { value: "claimed", label: "已認領" },
      { value: "running", label: "執行中" },
      { value: "waiting_for_input", label: "等待回覆" },
      { value: "succeeded", label: "成功" },
      { value: "failed", label: "失敗" },
      { value: "cancelled", label: "已取消" },
      { value: "lost", label: "失聯" },
    ],
  },
  {
    field: "risk",
    label: "風險",
    ops: ALL_OPS,
    options: [
      { value: "low", label: "低" },
      { value: "medium", label: "中" },
      { value: "high", label: "高" },
      { value: "critical", label: "極高" },
    ],
  },
  {
    field: "priority",
    label: "優先級",
    ops: ALL_OPS,
    options: [
      { value: "low", label: "低" },
      { value: "normal", label: "一般" },
      { value: "high", label: "高" },
    ],
  },
  {
    field: "card_kind",
    label: "卡片種類",
    ops: ALL_OPS,
    options: [
      { value: "implementation", label: "實作" },
      { value: "clarification", label: "釐清" },
      { value: "decomposition", label: "拆解" },
      { value: "mockup", label: "原型" },
    ],
  },
  {
    field: "is_blocked",
    label: "阻塞",
    // `eq`/`neq` only: `in` over two boolean values is a filter that matches everything,
    // and the server refuses it anyway (`is_blocked` carries `EQUALITY` alone).
    ops: EQUALITY,
    options: [
      { value: "true", label: "是" },
      { value: "false", label: "否" },
    ],
  },
];

export interface BuilderRow {
  field: string;
  op: "eq" | "neq" | "in" | "not_in";
  /** Always a list on screen; collapsed to a scalar for `eq`/`neq` on the way out. */
  values: string[];
}

export const OP_LABELS: Record<BuilderRow["op"], string> = {
  eq: "是",
  neq: "不是",
  in: "屬於",
  not_in: "不屬於",
};

function coerce(field: string, value: string): unknown {
  return field === "is_blocked" ? value === "true" : value;
}

/** Rows → the `f=` object, or null when there is nothing to filter by.
 *
 *  **`and` even for one row.** A single leaf is a legal filter and would be one fewer
 *  level of nesting, but then the shape changes as soon as somebody adds a second row —
 *  and every reader of `f=` (the chips' comparison, `isModified`, the saved view) would
 *  need to handle both. One shape costs a wrapper. */
export function buildFilter(
  rows: readonly BuilderRow[],
): Record<string, unknown> | null {
  const usable = rows.filter((row) => row.field && row.values.length > 0);
  if (usable.length === 0) return null;
  const leaves = usable.map((row) => ({
    field: row.field,
    op: row.op,
    value:
      row.op === "in" || row.op === "not_in"
        ? row.values.map((value) => coerce(row.field, value))
        : coerce(row.field, row.values[0]),
  }));
  return { and: leaves };
}

/** The inverse, best effort: `f=` → rows the builder can show.
 *
 *  **Best effort, and it says so.** A filter written by hand, or by a future version, can
 *  nest deeper than the builder draws. Rather than refusing to open, unreadable shapes
 *  come back as an empty row list and the caller shows "this filter was not built here" —
 *  the filter still applies, because the URL is what the server reads. Silently rewriting
 *  it to whatever the builder *could* express would change somebody's board on open. */
export function readBuilder(filter: Record<string, unknown> | null): {
  rows: BuilderRow[];
  representable: boolean;
} {
  if (!filter || Object.keys(filter).length === 0)
    return { rows: [], representable: true };
  const leaves = Array.isArray((filter as { and?: unknown }).and)
    ? ((filter as { and: unknown[] }).and as Record<string, unknown>[])
    : [filter as Record<string, unknown>];
  const rows: BuilderRow[] = [];
  for (const leaf of leaves) {
    const field = typeof leaf.field === "string" ? leaf.field : null;
    const op = typeof leaf.op === "string" ? leaf.op : null;
    const known = BUILDER_FIELDS.find((entry) => entry.field === field);
    if (!field || !op || !known) return { rows: [], representable: false };
    if (!known.ops.includes(op as BuilderRow["op"]))
      return { rows: [], representable: false };
    const raw = leaf.value;
    const values = (Array.isArray(raw) ? raw : [raw]).map((value) =>
      String(value),
    );
    if (values.some((value) => !known.options.some((o) => o.value === value)))
      return { rows: [], representable: false };
    rows.push({ field, op: op as BuilderRow["op"], values });
  }
  return { rows, representable: true };
}

# ADR 0005: Frontend foundation

Status: accepted (2026-07-22)

Amended by: ADR 0027 (2026-09-08) — the Naive UI clause only.

The prototype is narrowed to a dedicated `/poc/terminal` route and Cliora-branded shell. CSS custom properties in `tokens.css` are the palette source; ~~Naive UI overrides reference those variables instead of duplicating hex values~~ — **superseded by ADR 0027 §6**: Naive UI was never used (zero components, one type-only import in a file nothing imported) and the dependency is removed; components are hand-built and read `tokens.css` directly, with `theme/themes.ts` as the second, test-bound source for the two consumers that cannot take a custom property (xterm and Monaco). The terminal composable exclusively owns xterm, addons, socket, observer, timers, and cleanup.

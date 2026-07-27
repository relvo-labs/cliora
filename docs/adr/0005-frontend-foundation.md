# ADR 0005: Frontend foundation

Status: accepted (2026-07-22)

The prototype is narrowed to a dedicated `/poc/terminal` route and Cliora-branded shell. CSS custom properties in `tokens.css` are the palette source; Naive UI overrides reference those variables instead of duplicating hex values. The terminal composable exclusively owns xterm, addons, socket, observer, timers, and cleanup.

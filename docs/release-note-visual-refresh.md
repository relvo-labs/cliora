# Release note — visual refresh

Three things change the moment you open this version. They are first because
each one is something you will notice immediately, and a note that buries them
under a feature list has not told you.

## 1. The default theme is now dark

Cliora opens in **Graphite**, a dark theme. Previously the frame was light while
the terminal and the file preview were dark.

The reason is the terminal. It has always been dark, and a light frame around it
drew a hard, high-contrast edge around the one region you spend the day reading.

**A light theme is still here**: **Porcelain**. Both live in **個人設定**, which
you reach from the account menu at the top right — the same page now holds the
terminal font size, the file-panel width and the nav-collapse setting.

There are **three** choices, not two: Graphite, Porcelain, and **follow the
system**. The last is the default and you can go back to it at any time; the
page also tells you what your OS currently prefers. Once you choose explicitly,
your choice wins — including a dark app on a light OS, or the other way round.

Changing the theme in one tab changes it in all of them, so a tab holding a live
session recolours without losing its scrollback, its scroll position, or
anything you had half-typed.

Your choice is remembered **in this browser on this machine**. It does not follow
you to another machine or another browser — the settings page says so too. There is no server-side preference in
this release, deliberately: a visual change is not a reason to touch your
account.

## 2. The terminal is a little shorter, and the font is a little bigger

The session workspace gained a status bar (28px), the tab strip is now a fixed
height, and the work header is taller. The terminal's default font also went from
13px to 14px.

Measured at 1440×900, the CLI panel now shows **35 rows**, down from 44. The
platform's own floor is 30 rows, so there are five rows of headroom.

**On a smaller window, turn the font size down.** At 1024×768 the default 14px
gives 28 rows, which is fewer than we want. Use the **−** control in the status
bar, or the slider in 個人設定: 13px gives 30 rows at that size. It goes from
12px to 20px and is remembered.

The one thing worth knowing about why: the design specification said "line-height
1.6", which is the right number for UI body text and the wrong one for a
terminal, where it multiplies the character cell. Taken literally it would have
given **26** rows. We measured it rather than implementing it.

## 3. Only two of the five themes are supported

The design work produced five styles. **Two ship and are supported: Graphite and
Porcelain.** Midnight, Studio and Industrial have their colours recorded in the
code and pass the automated colour checks, but they are **not offered in the
menu**, their distinct layouts are not built, and no one has looked at them in a
browser. "Supports five themes" would not be true, so we do not say it.

Also not in this release: a compact information density, a command palette, and
cross-**device** preference sync. (Cross-**tab** does work — see above. The
difference is that nothing is stored on the server.)

---

## What else improved

**Readability, measurably.** Five contrast failures that had shipped are fixed:
the keyboard focus ring (2.85:1 → over 3:1 on every surface it can land on,
including the terminal), the **Terminate confirmation button** (4.09:1 → 6.20:1),
every input and secondary-button border (1.37:1 → over 3:1), and six of the eight
status badges, which were between 2.63:1 and 4.24:1 and are now all above 4.5:1.
Every colour pair the interface actually renders is now checked by a test with
its measured value, in both themes.

**Status is three facts, not one light.** The session workspace's status bar
reports the **session's state**, your **browser's connection**, and **who holds
control** separately. They used to be crowded into the work header, and a long
session name pushed them onto a second line. Keeping them apart matters:
"session running + disconnected" is not "session ended" — the first wants
Reconnect and on the second Reconnect does nothing.

**Every status badge says what it means in words**, and the words differ per
context. A session that has ended reads "已結束"; a browser that lost the process
it was watching reads "程序已結束". They used to share a colour rule by
coincidence.

**Personal settings has a home.** 個人設定, from the account menu: theme,
terminal font size, file-panel width, nav collapse, and one button that restores
all four. The account menu replaces the bare name-and-Sign-out block in the
header.

**Terminate moved.** It is in the **⋯ menu** on the session header rather than a
permanently visible red button next to Reconnect, and its confirmation now names
the session it will stop.

**Dialogs work from the keyboard.** Focus is held inside a dialog, Escape closes
it, and closing returns focus to the control that opened it. None of those three
worked before. A destructive confirmation opens with **Cancel** focused, so a
stray Enter cannot confirm it.

**The file panel can be resized, and it comes back.** Drag its edge (or focus the
handle and use the arrow keys) between 220px and 360px; the width is remembered.
Below 1024px it becomes a drawer with a button on the tab strip. Previously it
disappeared entirely below 1100px with no way at all to bring it back.

**The window can be narrower.** There are now four layouts: full at 1440px and
up, an icons-only rail from 1024px, a file drawer from 768px, and a menu below
that. **Reaching a control on a small screen does not change what you are allowed
to do** — the terminal's input permission is the same at 390px as at 1920px.

**The navigation icons are real icons.** The seven text symbols (`◫ ◈ ▣ ▷ ◉ ☰ ⇄`)
are Lucide icons now. They were not only inconsistent between platforms — a
screen reader read each one aloud as whatever the matched font happened to call
it.

**A skip link.** Tab once from the address bar to jump straight to the main
content instead of walking through the whole rail.

**Failures stay on screen.** Success messages appear briefly and leave. Failures —
an upload that was refused, a terminate that did not work, a connection that
dropped — stay in the region they belong to until you deal with them. A message
that removes itself after four seconds is one you may never have read.

**"No data" instead of zero.** A node that has not reported its CPU shows "no
data" rather than 0%. "0%" is a claim, and it is one an operator would act on.

**22 fewer dependencies.** `naive-ui` and its 21 transitive packages are gone.
They had never been used — no components, one type-only import, in a file nothing
imported.

## Unchanged

No authorization behaviour changed. No wire contract, no API, no database, no
daemon, no deployment configuration. Nothing about the two file-write paths, the
read-only preview, or the privileged-node posture labels — which still appear
before you type, where they were.

Full detail: `docs/vr-report.md`. Security review: `docs/security-review-p28.md`.

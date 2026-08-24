import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

// Wave 5's visible outcome (plan/26/00 §4b): the Drawer, opened from the board, with the
// conversation second and the execution settings expanded when one of them is why the card
// is stuck.
//
// The assertions are the ones a picture cannot make: that the conversation comes before
// the run panel, and that the execution block opens itself **and says which row to look
// at** for a card with no eligible runner.

const project = process.env.E2E_PX_PROJECT ?? "";
const user = process.env.E2E_ADMIN_USER ?? "admin";
const password = process.env.E2E_ADMIN_PASSWORD ?? "px-measure-pw-1";
const OUT = resolve(process.cwd(), "..", "artifacts/px/local/w5");

test.use({ viewport: { width: 1600, height: 1000 } });

async function signIn(page: Page): Promise<void> {
  await page.goto("/login");
  await page.locator('input[name="username"]').fill(user);
  await page.locator('input[name="password"]').fill(password);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page.locator('nav[aria-label="Primary"]')).toBeVisible();
}

test.beforeAll(() => mkdirSync(OUT, { recursive: true }));

test.describe("the Task Drawer", () => {
  test.skip(project === "", "set E2E_PX_PROJECT to the demo project id");

  test("opens over the board, conversation first, and explains a stuck card", async ({
    page,
  }) => {
    await signIn(page);
    await page.goto(`/projects/${project}/work`);

    // Open the card that is waiting on a person.
    await page
      .locator("[data-attention='waiting_for_your_input']")
      .first()
      .click();
    const drawer = page.locator("[data-task-drawer]");
    await expect(drawer).toBeVisible();
    // The board is still there behind it — the whole reason this is a Drawer.
    await expect(page.locator("[data-group='ready']")).toBeVisible();
    // And it says what is being waited on, without anybody expanding a log.
    await expect(drawer.locator("[data-waiting-note]")).toBeVisible();
    await page.screenshot({ path: `${OUT}/01-drawer-waiting.png` });

    // The conversation is above the run panel in the document, which is the reordering
    // this wave is about.
    const order = await drawer.evaluate((root) => {
      const anchor = root.querySelector("[data-conversation-anchor]");
      const agentPanel = root.querySelector(
        "[data-agent-panel], section:last-of-type",
      );
      if (!anchor || !agentPanel) return null;
      return anchor.compareDocumentPosition(agentPanel) &
        Node.DOCUMENT_POSITION_FOLLOWING
        ? "conversation-first"
        : "conversation-last";
    });
    expect(order).toBe("conversation-first");

    // Escape closes it and the board keeps its state.
    await drawer.press("Escape");
    await expect(drawer).toBeHidden();
    await expect(page).not.toHaveURL(/task=/);

    // A card with no eligible runner: the execution block opens itself and names the row.
    //
    // **Reached through the quick filter, not by looking for the badge on the board.** A
    // badge shows one card's *primary* level and a card can carry several signals; this
    // one is also awaiting a human decision, which outranks it (D107). So the level is a
    // fact about the card that the board does not display — and the chip is exactly the
    // control a person uses to find it. That the chip finds it is phase B working, which
    // is J15's first assertion.
    await page.locator("[data-chip='no-runner']").click();
    await expect(page).toHaveURL(/[?&]f=/);
    await page.locator("[data-card-ref] button").first().click();
    await expect(page.locator("[data-execution-block]")).toHaveAttribute(
      "data-open",
      "true",
    );
    await expect(page.locator("[data-execution-reason]")).toContainText("標籤");
    await page.screenshot({ path: `${OUT}/02-drawer-no-runner.png` });

    // The Drawer's own header carries the attention badge and a real link out.
    const drawerAgain = page.locator("[data-task-drawer]");
    await expect(drawerAgain.locator("[data-attention]")).toBeVisible();
    await expect(drawerAgain.locator("[data-drawer-newtab]")).toHaveAttribute(
      "target",
      "_blank",
    );
  });
});

// --- PX-46: the phone layout -------------------------------------------------------
//
// A viewport, not a device emulation: the three requirements are CSS and `matchMedia`
// decisions at 760px, and pretending to be an iPhone would add a user-agent string to a
// test about a breakpoint.
test.describe("the Drawer on a phone", () => {
  test.skip(project === "", "set E2E_PX_PROJECT to the demo project id");
  test.use({ viewport: { width: 390, height: 780 } });

  test("fixed header, the sidebar as an accordion, and the composer in reach", async ({
    page,
  }) => {
    await signIn(page);
    await page.goto(`/projects/${project}/work`);
    await page.locator("[data-card-ref] button").first().click();
    const drawer = page.locator("[data-task-drawer]");
    await expect(drawer).toBeVisible();
    await page.screenshot({ path: `${OUT}/03-mobile-drawer.png` });

    // **The sidebar is one line.** Below 760px the Drawer is one column, so the sidebar
    // lands *under* the conversation — eight rows of properties between the reader and the
    // composer is why it collapses.
    await expect(page.locator("[data-properties-toggle]")).toBeVisible();
    await expect(page.locator("dl.properties").first()).toBeHidden();
    await page.locator("[data-properties-toggle]").click();
    await expect(page.locator("dl.properties").first()).toBeVisible();

    // **The header stays put while the body scrolls.** Measured, not assumed: its
    // position before and after scrolling the panel has to be the same, and a header that
    // scrolled away would take the close button with it.
    const before = await drawer.locator("[data-drawer-head]").boundingBox();
    await drawer.locator("[data-drawer-body]").evaluate((node) => {
      node.scrollTop = node.scrollHeight;
    });
    const after = await drawer.locator("[data-drawer-head]").boundingBox();
    expect(after!.y).toBeCloseTo(before!.y, 0);

    // **The composer stays in reach while the thread is being read.** The conversation is
    // the reason somebody opens a card on a phone — an agent is stopped waiting for a
    // sentence — and a reply box that scrolls off the bottom of a forty-message thread is
    // a reply box that does not get used.
    //
    // *While the thread is being read*, not "always on screen": the composer is sticky
    // inside the conversation section, so it leaves when the reader scrolls past the
    // conversation entirely — to the artifacts, the gates, the readiness list. That is the
    // right behaviour and the reason it is `sticky` rather than `fixed`; a reply box
    // hovering over the gate list would be a floating control belonging to nothing on
    // screen. So the assertion scrolls to the conversation, the way a reader gets there.
    const composer = drawer.locator(".composer");
    if (await composer.count()) {
      await drawer
        .locator("[data-conversation-anchor]")
        .scrollIntoViewIfNeeded();
      const box = (await composer.boundingBox())!;
      const viewport = page.viewportSize()!;
      expect(box.y).toBeLessThan(viewport.height);
      expect(box.y + box.height).toBeGreaterThan(0);
    }
    await page.screenshot({ path: `${OUT}/04-mobile-composer.png` });
  });
});

import { test, expect } from "@playwright/test";
import { uniqueUser, registerAndLogin, openAccount, firstAccountNumber } from "./helpers.js";

test.describe("Accounts + transfers", () => {
  test("empty state on first login", async ({ page }) => {
    const u = uniqueUser("empty");
    await registerAndLogin(page, u);
    await expect(page.locator("#my-accounts .empty h3")).toContainText(/No accounts yet/);
  });

  test("open account shows a card with the starting balance and active status", async ({ page }) => {
    const u = uniqueUser("open");
    await registerAndLogin(page, u);
    await openAccount(page);
    const card = page.locator("#my-accounts .account-card").first();
    await expect(card.locator(".account-balance")).toHaveText("$100.00");
    await expect(card.locator(".account-status")).toHaveText("active");
    await expect(card.locator(".account-status")).toHaveClass(/active/);
  });

  test("multiple accounts render side by side", async ({ page }) => {
    const u = uniqueUser("multi");
    await registerAndLogin(page, u);
    await openAccount(page);
    await openAccount(page);
    await openAccount(page);
    await expect(page.locator("#my-accounts .account-card")).toHaveCount(3);
  });

  test("copy number button flips its label", async ({ page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    const u = uniqueUser("copy");
    await registerAndLogin(page, u);
    await openAccount(page);
    const btn = page.locator("#my-accounts .btn-copy").first();
    await expect(btn).toHaveText(/Copy number/);
    await btn.click();
    await expect(btn).toHaveText(/Copied ✓/);
  });

  test("sidebar navigation switches views", async ({ page }) => {
    const u = uniqueUser("nav");
    await registerAndLogin(page, u);
    await openAccount(page);

    await page.locator(".nav-item[data-nav=transfer]").click();
    await expect(page.locator("#transfer-view")).toHaveClass(/active/);
    await expect(page.locator("#transfer-view h1")).toContainText(/Send money/);

    await page.locator(".nav-item[data-nav=transactions]").click();
    await expect(page.locator("#transactions-view")).toHaveClass(/active/);
    await expect(page.locator("#transactions-view h1")).toContainText(/Transactions/);

    await page.locator(".nav-item[data-nav=accounts]").click();
    await expect(page.locator("#accounts-view")).toHaveClass(/active/);
    await expect(page.locator("#accounts-view h1")).toContainText(/My accounts/);
  });

  test("transfer form pre-populates the From-account select", async ({ page }) => {
    const u = uniqueUser("xfer");
    await registerAndLogin(page, u);
    await openAccount(page);
    await page.locator(".nav-item[data-nav=transfer]").click();
    const options = page.locator("#transfer-form select[name=from_account_id] option");
    await expect(options).toHaveCount(1);
  });

  test("transfer succeeds and both balances update", async ({ page, browser }) => {
    const alice = uniqueUser("send_a");
    const bob = uniqueUser("send_b");
    const bobCtx = await browser.newContext({ ignoreHTTPSErrors: true });
    const bobPage = await bobCtx.newPage();
    await registerAndLogin(bobPage, bob);
    await openAccount(bobPage);
    const bobAccountNumber = await firstAccountNumber(bobPage);
    await bobCtx.close();

    await registerAndLogin(page, alice);
    await openAccount(page);
    await page.locator(".nav-item[data-nav=transfer]").click();
    await page.locator("#transfer-form input[name=to_account_number]").fill(bobAccountNumber);
    await page.locator("#transfer-form input[name=amount]").fill("25");
    await page.locator("#transfer-form").getByRole("button", { name: /^Send$/ }).click();

    await expect(page.locator(".tx-receipt-badge")).toHaveText(/Sent/);
    await expect(page.locator(".tx-receipt-amount")).toHaveText("-$25.00");
    // Source balance dropped to $75
    await page.locator(".nav-item[data-nav=accounts]").click();
    await expect(page.locator("#my-accounts .account-balance").first()).toHaveText("$75.00");
  });

  test("transfer larger than balance shows insufficient-funds error", async ({ page, browser }) => {
    const alice = uniqueUser("over_a");
    const bob = uniqueUser("over_b");
    const bobCtx = await browser.newContext({ ignoreHTTPSErrors: true });
    const bobPage = await bobCtx.newPage();
    await registerAndLogin(bobPage, bob);
    await openAccount(bobPage);
    const bobAccountNumber = await firstAccountNumber(bobPage);
    await bobCtx.close();

    await registerAndLogin(page, alice);
    await openAccount(page);
    await page.locator(".nav-item[data-nav=transfer]").click();
    await page.locator("#transfer-form input[name=to_account_number]").fill(bobAccountNumber);
    // Starting balance is $100; $1000 is well over.
    await page.locator("#transfer-form input[name=amount]").fill("1000");
    await page.locator("#transfer-form").getByRole("button", { name: /^Send$/ }).click();

    await expect(page.locator("#global-error")).toBeVisible();
    await expect(page.locator("#global-error")).toContainText(/insufficient funds/i);
  });

  test("transfer to unknown account number shows account-not-found error", async ({ page }) => {
    const u = uniqueUser("nowhere");
    await registerAndLogin(page, u);
    await openAccount(page);
    await page.locator(".nav-item[data-nav=transfer]").click();
    await page.locator("#transfer-form input[name=to_account_number]").fill("000000000000");
    await page.locator("#transfer-form input[name=amount]").fill("5");
    await page.locator("#transfer-form").getByRole("button", { name: /^Send$/ }).click();
    await expect(page.locator("#global-error")).toBeVisible();
    await expect(page.locator("#global-error")).toContainText(/not found/i);
  });

  test("transactions view shows empty state when the account has no transfers", async ({ page }) => {
    const u = uniqueUser("txempty");
    await registerAndLogin(page, u);
    await openAccount(page);
    await page.locator(".nav-item[data-nav=transactions]").click();
    await expect(page.locator("#tx-list .empty h3")).toContainText(/No transactions yet/);
  });
});

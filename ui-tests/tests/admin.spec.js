import { test, expect } from "@playwright/test";
import { ADMIN, uniqueUser, login, registerAndLogin, openAccount, logout, firstAccountNumber } from "./helpers.js";

test.describe("Admin role", () => {
  test("customer does NOT see the All accounts nav item", async ({ page }) => {
    const u = uniqueUser("customer");
    await registerAndLogin(page, u);
    const adminNav = page.locator(".nav-item[data-nav=admin]");
    await expect(adminNav).toBeHidden();
    await expect(page.locator("#user-role")).toHaveText("customer");
    await expect(page.locator("#user-role")).not.toHaveClass(/role-admin/);
  });

  test("admin sees the All accounts nav item + purple role badge", async ({ page }) => {
    await login(page, ADMIN);
    await expect(page.locator("#user-role")).toHaveText("admin");
    await expect(page.locator("#user-role")).toHaveClass(/role-admin/);
    await expect(page.locator(".nav-item[data-nav=admin]")).toBeVisible();
  });

  test("admin can see All accounts view with Owner label (customer view has no Owner)", async ({ page, browser }) => {
    const seedCtx = await browser.newContext({ ignoreHTTPSErrors: true });
    const seedPage = await seedCtx.newPage();
    const seed = uniqueUser("seed");
    await registerAndLogin(seedPage, seed);
    await openAccount(seedPage);
    await seedCtx.close();

    await login(page, ADMIN);
    await page.locator(".nav-item[data-nav=admin]").click();
    await expect(page.locator("#admin-view")).toHaveClass(/active/);
    const cards = page.locator("#all-accounts .account-card");
    await expect(cards.first()).toBeVisible();
    // Admin view exposes an "Owner" label — customer view hides it.
    await expect(cards.first().locator(".account-meta")).toContainText(/Owner/);
  });

  test("admin can freeze a customer's account; status pill flips to frozen", async ({ page, browser }) => {
    const cust = uniqueUser("freezee");
    const custCtx = await browser.newContext({ ignoreHTTPSErrors: true });
    const custPage = await custCtx.newPage();
    await registerAndLogin(custPage, cust);
    await openAccount(custPage);
    const targetNumber = await firstAccountNumber(custPage);
    await custCtx.close();

    await login(page, ADMIN);
    await page.locator(".nav-item[data-nav=admin]").click();

    page.once("dialog", (d) => d.accept());
    const targetCard = page
      .locator("#all-accounts .account-card")
      .filter({ hasText: targetNumber });
    await targetCard.locator(".btn-freeze").click();
    await expect(
      page.locator("#all-accounts .account-card").filter({ hasText: targetNumber })
        .locator(".account-status")
    ).toHaveText("frozen");
  });

  test("frozen account cannot transfer; error banner appears", async ({ page, browser }) => {
    const cust = uniqueUser("frozen_actor");
    const dest = uniqueUser("dest");

    const destCtx = await browser.newContext({ ignoreHTTPSErrors: true });
    const destPage = await destCtx.newPage();
    await registerAndLogin(destPage, dest);
    await openAccount(destPage);
    const destNumber = await firstAccountNumber(destPage);
    await destCtx.close();

    const targetCtx = await browser.newContext({ ignoreHTTPSErrors: true });
    const targetPage = await targetCtx.newPage();
    await registerAndLogin(targetPage, cust);
    await openAccount(targetPage);
    const targetNumber = await firstAccountNumber(targetPage);
    await targetCtx.close();

    await login(page, ADMIN);
    await page.locator(".nav-item[data-nav=admin]").click();
    page.once("dialog", (d) => d.accept());
    await page
      .locator("#all-accounts .account-card")
      .filter({ hasText: targetNumber })
      .locator(".btn-freeze")
      .click();
    await logout(page);

    await login(page, cust);
    await page.locator(".nav-item[data-nav=transfer]").click();
    await page.locator("#transfer-form input[name=to_account_number]").fill(destNumber);
    await page.locator("#transfer-form input[name=amount]").fill("5");
    await page.locator("#transfer-form").getByRole("button", { name: /^Send$/ }).click();

    await expect(page.locator("#global-error")).toBeVisible();
    await expect(page.locator("#global-error")).toContainText(/frozen/i);
  });

  test("admin can unfreeze a frozen account; status pill flips back to active", async ({ page, browser }) => {
    const cust = uniqueUser("unfreezee");
    const custCtx = await browser.newContext({ ignoreHTTPSErrors: true });
    const custPage = await custCtx.newPage();
    await registerAndLogin(custPage, cust);
    await openAccount(custPage);
    const targetNumber = await firstAccountNumber(custPage);
    await custCtx.close();

    await login(page, ADMIN);
    await page.locator(".nav-item[data-nav=admin]").click();

    const targetCard = () =>
      page.locator("#all-accounts .account-card").filter({ hasText: targetNumber });

    page.once("dialog", (d) => d.accept());
    await targetCard().locator(".btn-freeze").click();
    await expect(targetCard().locator(".account-status")).toHaveText("frozen");

    page.once("dialog", (d) => d.accept());
    await targetCard().locator(".btn-unfreeze").click();
    await expect(targetCard().locator(".account-status")).toHaveText("active");
    // Freeze button is back; Unfreeze is gone.
    await expect(targetCard().locator(".btn-freeze")).toBeVisible();
    await expect(targetCard().locator(".btn-unfreeze")).toHaveCount(0);
  });

  test("previously-frozen account can transfer again after unfreeze", async ({ page, browser }) => {
    const cust = uniqueUser("thaw_actor");
    const dest = uniqueUser("thaw_dest");

    const destCtx = await browser.newContext({ ignoreHTTPSErrors: true });
    const destPage = await destCtx.newPage();
    await registerAndLogin(destPage, dest);
    await openAccount(destPage);
    const destNumber = await firstAccountNumber(destPage);
    await destCtx.close();

    const custCtx = await browser.newContext({ ignoreHTTPSErrors: true });
    const custPage = await custCtx.newPage();
    await registerAndLogin(custPage, cust);
    await openAccount(custPage);
    const targetNumber = await firstAccountNumber(custPage);
    await custCtx.close();

    // Admin freezes then unfreezes
    await login(page, ADMIN);
    await page.locator(".nav-item[data-nav=admin]").click();
    const targetCard = () =>
      page.locator("#all-accounts .account-card").filter({ hasText: targetNumber });
    page.once("dialog", (d) => d.accept());
    await targetCard().locator(".btn-freeze").click();
    await expect(targetCard().locator(".account-status")).toHaveText("frozen");
    page.once("dialog", (d) => d.accept());
    await targetCard().locator(".btn-unfreeze").click();
    await expect(targetCard().locator(".account-status")).toHaveText("active");
    await logout(page);

    // Customer signs back in — transfer now succeeds
    await login(page, cust);
    await page.locator(".nav-item[data-nav=transfer]").click();
    await page.locator("#transfer-form input[name=to_account_number]").fill(destNumber);
    await page.locator("#transfer-form input[name=amount]").fill("5");
    await page.locator("#transfer-form").getByRole("button", { name: /^Send$/ }).click();
    await expect(page.locator(".tx-receipt-badge")).toHaveText(/Sent/);
  });

  test("customer hitting admin-only endpoint fails at the API (RBAC)", async ({ page, request }) => {
    const u = uniqueUser("rbac");
    await registerAndLogin(page, u);

    const loginResp = await request.post("/login", {
      data: { username: u.username, password: u.password },
    });
    const { access_token } = await loginResp.json();
    const res = await request.get("/banking/accounts", {
      headers: { authorization: `Bearer ${access_token}` },
    });
    expect(res.status()).toBe(403);
  });
});

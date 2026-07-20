import { expect } from "@playwright/test";

export const ADMIN = { username: "admin", password: "admin-demo-do-not-ship" };

export function uniqueUser(prefix = "user") {
  const stamp = Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
  return { username: `${prefix}_${stamp}`, password: "correct-horse-battery-staple" };
}

export async function registerAndLogin(page, user) {
  await page.goto("/");
  await page.getByRole("tab", { name: /Create account/i }).click();
  const form = page.locator("#register-form");
  await form.locator("input[name=username]").fill(user.username);
  await form.locator("input[name=password]").fill(user.password);
  await form.getByRole("button", { name: /Create account/i }).click();
  await page.waitForURL(/\/app(\.html)?$/);
}

export async function login(page, user) {
  await page.goto("/");
  const form = page.locator("#login-form");
  await form.locator("input[name=username]").fill(user.username);
  await form.locator("input[name=password]").fill(user.password);
  await form.getByRole("button", { name: /Sign in/i }).click();
  await page.waitForURL(/\/app(\.html)?$/);
}

export async function logout(page) {
  await page.locator("#logout-btn").click();
  await page.waitForURL(/^https:\/\/localhost:8443\/$/);
}

export async function openAccount(page) {
  const before = await page.locator("#my-accounts .account-card").count();
  await page.locator("#open-account-btn").click();
  // loadMyAccounts() runs unawaited from the click handler: wait for the
  // card count to strictly increment before returning.
  await expect(page.locator("#my-accounts .account-card")).toHaveCount(before + 1);
}

export async function firstAccountNumber(page, selector = "#my-accounts") {
  const card = page.locator(`${selector} .account-card`).first();
  await card.waitFor();
  // First meta row is "Account number" — the digits-only string.
  const numText = await card.locator(".account-meta .value").first().innerText();
  return numText.trim();
}

export async function firstAccountFreezeId(page, selector = "#all-accounts") {
  const card = page.locator(`${selector} .account-card`).first();
  await card.waitFor();
  return card.locator(".btn-freeze").first().getAttribute("data-id");
}

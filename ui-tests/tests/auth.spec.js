import { test, expect } from "@playwright/test";
import { ADMIN, uniqueUser, login, registerAndLogin, logout } from "./helpers.js";

test.describe("Auth pages", () => {
  test("login page loads with brand + segmented tabs", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveTitle(/Sign in — Secure Bank/);
    await expect(page.locator(".brand-name")).toContainText("Secure Bank");
    await expect(page.getByRole("tab", { name: /Sign in/i })).toBeVisible();
    await expect(page.getByRole("tab", { name: /Create account/i })).toBeVisible();
    // Login form is the default active pane
    await expect(page.locator("#login-form")).toHaveClass(/active/);
  });

  test("switching to Create account swaps the form", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("tab", { name: /Create account/i }).click();
    await expect(page.locator("#register-form")).toHaveClass(/active/);
    await expect(page.locator("#login-form")).not.toHaveClass(/active/);
  });

  test("register → auto-login → lands on /app", async ({ page }) => {
    const u = uniqueUser("alice");
    await registerAndLogin(page, u);
    await expect(page).toHaveURL(/\/app(\.html)?$/);
    await expect(page.locator("#user-name")).toHaveText(u.username);
    await expect(page.locator("#user-role")).toHaveText("customer");
  });

  test("wrong password shows error banner and stays on /", async ({ page }) => {
    await page.goto("/");
    await page.locator("#login-form input[name=username]").fill("nobody_such_user");
    await page.locator("#login-form input[name=password]").fill("wrong-password-1234");
    await page.locator("#login-form").getByRole("button", { name: /Sign in/i }).click();
    await expect(page.locator("#auth-error")).toBeVisible();
    await expect(page.locator("#auth-error")).toContainText(/invalid credentials/i);
    await expect(page).toHaveURL(/localhost:8443\/$/);
  });

  test("session resumes: reload on /app stays on /app", async ({ page }) => {
    const u = uniqueUser("resume");
    await registerAndLogin(page, u);
    await page.reload();
    await expect(page).toHaveURL(/\/app(\.html)?$/);
    await expect(page.locator("#user-name")).toHaveText(u.username);
  });

  test("visiting / with an active session redirects to /app", async ({ page }) => {
    const u = uniqueUser("resume2");
    await registerAndLogin(page, u);
    await page.goto("/");
    await expect(page).toHaveURL(/\/app(\.html)?$/);
  });

  test("logout returns to / and clears the session", async ({ page }) => {
    const u = uniqueUser("bye");
    await registerAndLogin(page, u);
    await logout(page);
    await expect(page).toHaveURL(/localhost:8443\/$/);
    // Session cleared: hitting /app should bounce back to /
    await page.goto("/app");
    await expect(page).toHaveURL(/localhost:8443\/$/);
  });

  test("visiting /app unauthenticated redirects to /", async ({ page }) => {
    await page.goto("/app");
    await expect(page).toHaveURL(/localhost:8443\/$/);
  });

  test("re-login from the login page", async ({ page }) => {
    const u = uniqueUser("reuse");
    await registerAndLogin(page, u);
    await logout(page);
    await login(page, u);
    await expect(page.locator("#user-name")).toHaveText(u.username);
  });
});

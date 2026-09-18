const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const fs = require("node:fs"),
  path = require("node:path"),
  assert = require("node:assert/strict");
(async () => {
  const browser = await chromium.launch({ headless: true, channel: "chrome" });
  const root = path.resolve(__dirname, "../../src/agentdevstu/web/static/dist");
  const screenshots = process.env.SCREENSHOT_DIR;
  const errors = [],
    requests = [];
  let admin = true,
    empty = false;
  const today = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
  const at = today + "T09:20:00+08:00";
  const totals = {
    calls: 42,
    operations: 12,
    input_tokens: 128400,
    output_tokens: 21600,
    total_tokens: 150000,
    complete_calls: 40,
    unknown_calls: 2,
    failed_calls: 1,
    interrupted_calls: 0,
    completeness: 40 / 42,
  };
  const row = {
    id: "call1",
    operation_id: "op1",
    step_id: "s1",
    parent_step_id: "root",
    started_at: at,
    source: "conversation",
    action: "reply",
    user_name: "李工",
    agent_name: "产品分析师",
    provider: "DeepSeek",
    requested_model: "deepseek-chat",
    actual_model: "deepseek-chat",
    input_tokens: 1200,
    output_tokens: 300,
    total_tokens: 1500,
    status: "success",
    usage_status: "complete",
    duration_ms: 2340,
    retry_count: 0,
    trigger: "user",
  };
  async function setup(page) {
    page.on("pageerror", (e) => errors.push(e.message));
    await page.route("http://usage.local/**", async (route) => {
      const u = new URL(route.request().url());
      if (u.pathname.startsWith("/api/")) {
        requests.push(u);
        let data = {};
        if (u.pathname === "/api/auth/me")
          data = {
            id: "admin",
            display_name: "管理员",
            username: "admin",
            is_superadmin: admin,
            system_permissions: admin ? ["config.manage"] : [],
            memberships: [{ workspace_id: "ws", permissions: ["agent.use"] }],
          };
        else if (u.pathname === "/api/workspaces")
          data = [{ id: "ws", name: "产品中心" }];
        else if (u.pathname.endsWith("/usage/options"))
          data = {
            sources: { conversation: "对话", meeting: "会议" },
            actions: { reply: "生成回复", memory_extract: "记忆提取" },
            statuses: { success: "成功", failed: "失败", running: "进行中" },
            users: [{ value: "u1", label: "李工" }],
            agents: [{ value: "a1", label: "产品分析师" }],
            providers: [{ value: "DeepSeek", label: "DeepSeek" }],
            models: [{ value: "deepseek-chat", label: "deepseek-chat" }],
            workspaces: [{ value: "ws", label: "产品中心" }],
          };
        else if (u.pathname.endsWith("/usage/summary"))
          data = {
            totals: empty
              ? { calls: 0, operations: 0, complete_calls: 0, unknown_calls: 0 }
              : totals,
            trend: empty
              ? []
              : [{ bucket: today + "T00:00:00+08:00", ...totals }],
            health: { pending_records: 0, last_error: null, write_failures: 0 },
          };
        else if (u.pathname.endsWith("/usage/groups")) {
          let d = u.searchParams.get("dimension");
          data = {
            total: empty ? 0 : 1,
            items: empty
              ? []
              : [
                  {
                    key: d === "model" ? "deepseek-chat" : "conversation",
                    label: d === "model" ? "deepseek-chat" : "对话",
                    ...totals,
                    avg_tokens: 3750,
                  },
                ],
          };
        } else if (u.pathname.endsWith("/usage/calls"))
          data = { total: empty ? 0 : 1, items: empty ? [] : [row] };
        else if (u.pathname.includes("/usage/operations/"))
          data = {
            operation: {
              id: "op1",
              source: "conversation",
              user_name: "李工",
              started_at: at,
              object_type: "conversation",
              object_id: "conv1",
            },
            total: 1,
            total_tokens: 1500,
            items: [row],
          };
        else if (u.pathname.endsWith("/usage/export"))
          return route.fulfill({
            body: "调用ID,总Token\ncall1,1500",
            headers: {
              "content-type": "text/csv",
              "content-disposition": 'attachment; filename="usage.csv"',
            },
          });
        return route.fulfill({ json: data });
      }
      const file = u.pathname.startsWith("/static/dist/")
        ? path.join(root, u.pathname.slice(13))
        : path.join(root, "index.html");
      return route.fulfill({
        body: fs.readFileSync(file),
        contentType: file.endsWith(".js")
          ? "application/javascript"
          : file.endsWith(".css")
            ? "text/css"
            : "text/html",
      });
    });
  }
  try {
    const page = await browser.newPage({
      viewport: { width: 1440, height: 1100 },
    });
    await setup(page);
    await page.goto("http://usage.local/model-usage");
    await page.getByText("Token 消耗趋势", { exact: true }).waitFor();
    assert(
      (await page
        .getByRole("link", { name: "模型用量", exact: true })
        .count()) === 1,
    );
    await page.getByRole("button", { name: "更多筛选", exact: true }).click();
    await page
      .getByLabel("动作", { exact: true })
      .selectOption("memory_extract");
    await page.getByRole("button", { name: "查询", exact: true }).click();
    await page.getByRole("button", { name: "查询", exact: true }).waitFor();
    await page.waitForFunction(
      () => !document.querySelector(".filter-footer .btn").disabled,
    );
    assert(
      requests.some(
        (u) =>
          u.pathname.endsWith("/summary") &&
          u.searchParams.get("action") === "memory_extract",
      ),
    );
    await page.getByRole("button", { name: "重置", exact: true }).click();
    await page.getByRole("button", { name: "查询", exact: true }).click();
    await page.waitForFunction(
      () => !document.querySelector(".filter-footer .btn").disabled,
    );
    await page.getByRole("button", { name: "收起筛选", exact: true }).click();
    if (screenshots) {
      fs.mkdirSync(screenshots, { recursive: true });
      for (const appearance of ["light", "dark"]) {
        await page.evaluate(
          (v) =>
            window.dispatchEvent(
              new CustomEvent("appearance-change", { detail: v }),
            ),
          appearance,
        );
        assert(
          (await page.evaluate(
            () => document.documentElement.dataset.theme,
          )) === appearance,
        );
        await page.screenshot({
          path: path.join(screenshots, `usage-${appearance}.png`),
          fullPage: true,
          animations: "disabled",
        });
      }
    }
    await page.getByRole("button", { name: "分类统计", exact: true }).click();
    await page
      .getByRole("heading", { name: "分类统计", exact: true })
      .waitFor();
    await page.getByRole("button", { name: "调用审计", exact: true }).click();
    await page.getByRole("button", { name: "操作详情", exact: true }).click();
    await page.getByText("业务操作详情", { exact: true }).waitFor();
    await page.getByText("输入 1,200", { exact: true }).waitFor();
    await page.keyboard.press("Escape");
    assert(!(await page.getByRole("dialog").isVisible()));
    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "导出明细", exact: true }).click();
    const download = await downloadPromise;
    assert(download.suggestedFilename().endsWith(".csv"));
    await page.getByRole("button", { name: "用量总览", exact: true }).click();
    await page.emulateMedia({ colorScheme: "dark" });
    await page.evaluate(() =>
      window.dispatchEvent(
        new CustomEvent("appearance-change", { detail: "system" }),
      ),
    );
    await page.waitForFunction(
      () => document.documentElement.dataset.theme === "dark",
    );
    await page.setViewportSize({ width: 390, height: 844 });
    assert(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    );
    if (screenshots)
      await page.screenshot({
        path: path.join(screenshots, "usage-mobile.png"),
        fullPage: true,
        animations: "disabled",
      });
    empty = true;
    await page.getByRole("button", { name: "刷新", exact: true }).click();
    await page.getByText("当前范围暂无模型调用", { exact: true }).waitFor();
    admin = false;
    const member = await browser.newPage();
    await setup(member);
    await member.goto("http://usage.local/model-usage");
    await member.waitForURL("http://usage.local/");
    assert(
      (await member
        .getByRole("link", { name: "模型用量", exact: true })
        .count()) === 0,
    );
    assert.deepEqual(errors, []);
    console.log(
      "Usage UI: filters, tabs, details, CSV, themes, mobile, empty state and member guard passed.",
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});

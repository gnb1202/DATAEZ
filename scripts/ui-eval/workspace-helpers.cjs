// Shared navigation for the store workspace. Opening chat preserves its session.
async function openChat(page) {
  if (!await page.locator('#workspace-chat-toggle').count()) {
    await page.getByRole('navigation', { name: '작업 메뉴' }).getByRole('button', { name: 'AI 분석', exact: true }).click();
    await page.getByRole('tab', { name: 'AI 분석', exact: true }).click();
  }
  const toggle = page.locator('#workspace-chat-toggle');
  await toggle.waitFor();
  if (await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click();
  await page.getByRole('textbox', { name: '분석 요청', exact: true }).waitFor();
}
async function openLatestAnalysis(page) {
  await page.getByRole('button', { name: '분석 이력', exact: true }).click();
  await page.locator('#workspace-main .divide-y > button').first().click();
  await page.waitForFunction(() => !document.querySelector('textarea')?.disabled);
}
module.exports = { openChat, openLatestAnalysis };

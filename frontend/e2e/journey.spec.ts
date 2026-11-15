import { expect, test, type Page } from '@playwright/test'

// 1×1 PNG
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==', 'base64')

async function signup(page: Page) {
  const email = `e2e${Date.now()}${Math.floor(Math.random() * 1e4)}@example.com`
  await page.goto('/signup')
  await page.getByLabel('Name').fill('E2E Grower')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill('e2e-password-123')
  await page.getByRole('button', { name: 'Create account' }).click()
  await expect(page).toHaveURL(/\/farms\/new/)
}

async function wizard(page: Page, name: string, budget = '200000') {
  await page.getByLabel('Farm name').fill(name)
  await page.getByRole('button', { name: 'Save and continue' }).click()
  await expect(page.getByRole('heading', { name: 'Location' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Enable location' })).toBeVisible()
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page.getByRole('heading', { name: 'Room photo' })).toBeVisible()
  await page.getByTestId('photo-input').setInputFiles({ name: 'room.png', mimeType: 'image/png', buffer: PNG })
  await expect(page.getByText('room.png')).toBeVisible()
  await expect(page.getByText('AI photo reading is off')).toBeVisible()
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page.getByRole('heading', { name: 'Room size' })).toBeVisible()
  await page.getByLabel('Units').selectOption('ft')
  await page.getByLabel('Length').fill('10')
  await page.getByLabel('Width').fill('8')
  await page.getByLabel('Ceiling height').fill('9')
  await page.getByLabel('Typical room temperature').fill('21')
  await expect(page.getByText('Planning grid: 10 × 8 cells of 1 ft.')).toBeVisible()
  await page.getByRole('button', { name: 'Save and continue' }).click()
  await expect(page.getByRole('heading', { name: 'Budget' })).toBeVisible()
  await expect(page.getByLabel('Currency')).toHaveValue('INR')
  await page.getByLabel(/total budget/).fill(budget)
  await page.getByRole('button', { name: 'Save and continue' }).click()
  await expect(page.getByRole('heading', { name: 'Review' })).toBeVisible()
}

test('main journey: plan → build → monitor → optimize → export', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  await signup(page)
  await wizard(page, 'E2E spare room')
  const farmId = page.url().match(/farms\/(\d+)/)![1]

  // budget plan: everything chosen from the budget, never over it
  await page.getByRole('button', { name: 'Create my budget plan' }).click()
  await expect(page).toHaveURL(/\/plan$/)
  await expect(page.getByText(/of ₹2,00,000 budget|of ₹200,000 budget/)).toBeVisible()
  await expect(page.getByText('Options the planner compared')).toBeVisible()
  const planFarm = await (await page.request.get(`/api/farms/${farmId}`)).json()
  const planDesign = await (await page.request.get(`/api/designs/${planFarm.active_design_id}`)).json()
  expect(planDesign.origin).toBe('BUDGET_PLAN')
  expect(planDesign.cost_totals.setup_total).toBeLessThanOrEqual(200000)
  expect(planDesign.validation.valid).toBe(true)
  await page.goto(`/farms/${farmId}/space`)

  // obstacles + door zone
  await page.getByLabel('Obstacle type').selectOption('DOOR')
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await expect(page.getByRole('img', { name: /with 0 racks and 1 obstacles/ })).toBeVisible()
  await page.getByLabel('Obstacle type').selectOption('PILLAR')
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await expect.poll(async () => (await (await page.request.get(`/api/farms/${farmId}/obstacles`)).json()).length).toBe(2)

  // grid: 10 × 8 = 80
  await page.goto(`/farms/${farmId}/grid`)
  const gridPanel = page.locator('section', { hasText: 'Grid size' })
  await expect(gridPanel.getByText('Full cells', { exact: true })).toBeVisible()
  await expect(gridPanel.getByText('80', { exact: true })).toBeVisible()
  await expect(gridPanel.getByText('10', { exact: true })).toBeVisible()
  await expect(gridPanel.getByText('8', { exact: true })).toBeVisible()

  // generate + save layout
  await page.goto(`/farms/${farmId}/layout`)
  await page.getByRole('radio', { name: 'Generate new' }).click()
  await page.getByLabel('Walkway width').fill('2.5')
  await page.getByRole('button', { name: 'Generate layouts' }).click()
  await expect(page.getByText('Best score')).toBeVisible()
  await page.getByRole('button', { name: 'Save this layout' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Save layout' }).click()
  await expect(page.getByText('All hard constraints pass')).toBeVisible()
  await expect(page.getByText('Valid', { exact: true })).toBeVisible()

  // independent check via API: no overlaps, no door-zone or access violations
  const farm = await (await page.request.get(`/api/farms/${farmId}`)).json()
  const design = await (await page.request.get(`/api/designs/${farm.active_design_id}`)).json()
  expect(design.validation.valid).toBe(true)
  expect(design.validation.violations).toEqual([])
  const r = design.racks as { x: number; y: number; w: number; d: number }[]
  for (let i = 0; i < r.length; i++) for (let j = i + 1; j < r.length; j++) {
    const a = r[i], b = r[j]
    const overlap = a.x < b.x + b.w - 1e-6 && b.x < a.x + a.w - 1e-6 && a.y < b.y + b.d - 1e-6 && b.y < a.y + a.d - 1e-6
    expect(overlap).toBe(false)
  }

  // save and reopen
  await page.reload()
  await expect(page.getByRole('button', { name: /^Rack R1/ })).toBeVisible()
  expect(await page.getByRole('button', { name: /^Rack R\d/ }).count()).toBe(r.length)

  // 2D and 3D
  await page.goto(`/farms/${farmId}/view`)
  await page.getByRole('radio', { name: '2D plan' }).click()
  await expect(page.getByRole('img', { name: new RegExp(`${r.length} racks`) })).toBeVisible()
  await page.getByRole('radio', { name: '3D model' }).click()
  await expect(page.locator('canvas')).toBeVisible()

  // crop recommendation
  await page.goto(`/farms/${farmId}/crops`)
  await expect(page.getByText('Top match')).toBeVisible()
  await expect(page.getByText('In design')).toBeVisible()

  // edit a cost and verify the total changes
  await page.goto(`/farms/${farmId}/costs`)
  const setup = page.locator('div', { hasText: /^Setup total/ }).locator('xpath=..').first()
  const before = await (await page.request.get(`/api/designs/${farm.active_design_id}/costs`)).json()
  const rackLine = before.items.find((i: any) => i.key === 'racks')
  const price = page.getByLabel(/Unit price of Shelving rack/)
  await price.fill(String(rackLine.unit_price + 100))
  await price.press('Enter')
  const expected = before.totals.setup_total + 100 * rackLine.quantity
  await expect.poll(async () => (await (await page.request.get(`/api/designs/${farm.active_design_id}/costs`)).json()).totals.setup_total).toBeCloseTo(expected, 1)
  await expect(setup).toBeVisible()
  await expect(page.getByText(new RegExp(`₹${Math.round(expected).toLocaleString('en-US')}|₹${Math.round(expected).toLocaleString('en-IN')}`)).first()).toBeVisible()

  // what-if scenario
  await page.goto(`/farms/${farmId}/scenarios`)
  await page.getByLabel('Scenario name').fill('Three levels')
  await page.getByLabel('Levels').fill('3')
  await page.getByRole('button', { name: 'Run scenario' }).click()
  await expect(page.getByText('Preview (not saved)')).toBeVisible()
  await expect(page.getByRole('cell', { name: 'Plant sites' })).toBeVisible()
  await page.getByRole('button', { name: 'Save scenario' }).click()
  await expect(page.getByRole('button', { name: /Three levels/ })).toBeVisible()

  // simulator: timestamped SIMULATED records persist
  await page.goto(`/farms/${farmId}/monitor`)
  await page.getByRole('button', { name: 'Start' }).click()
  await expect(page.getByText(/Simulator running ·/)).toBeVisible()
  await expect.poll(async () => (await (await page.request.get(`/api/farms/${farmId}/sensors?limit=5`)).json()).total, { timeout: 20_000 }).toBeGreaterThanOrEqual(2)
  const recs = (await (await page.request.get(`/api/farms/${farmId}/sensors?limit=5`)).json()).items
  expect(recs.every((x: any) => x.source_type === 'SIMULATED' && !Number.isNaN(Date.parse(x.ts)))).toBe(true)
  await page.getByRole('button', { name: 'Pause' }).click()
  await expect(page.getByText(/Simulator paused/).first()).toBeVisible()

  // test alert
  await page.getByRole('button', { name: 'Trigger a test alert' }).click()
  await expect(page.getByText(/open alert/).first()).toBeVisible()
  await page.goto(`/farms/${farmId}/insights`)
  await expect(page.getByText(/pH .* is above the critical limit/).first()).toBeVisible()

  // report export
  await page.goto(`/farms/${farmId}/report`)
  await expect(page.getByText('Assumptions & limitations')).toBeVisible()
  const [dl] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: 'Download PDF' }).click()])
  expect(dl.suggestedFilename()).toMatch(/\.pdf$/)

  expect(errors).toEqual([])
})

test('infeasible design is explained, not silently relaxed', async ({ page }) => {
  await signup(page)
  await wizard(page, 'E2E tiny room')
  const farmId = page.url().match(/farms\/(\d+)/)![1]
  await page.getByRole('button', { name: 'Create my budget plan' }).click()
  await expect(page).toHaveURL(/\/plan$/)
  await page.goto(`/farms/${farmId}/layout`)
  await page.getByRole('radio', { name: 'Generate new' }).click()
  await page.getByLabel('Length', { exact: true }).fill('20')
  await page.getByRole('button', { name: 'Generate layouts' }).click()
  await expect(page.getByText('No layout fits with these settings')).toBeVisible()
  await expect(page.getByText(/exceeds the longest usable wall/)).toBeVisible()
})

test('invalid input is rejected with a clear message', async ({ page }) => {
  await signup(page)
  await page.getByLabel('Farm name').fill('Validation')
  await page.getByRole('button', { name: 'Save and continue' }).click()
  await expect(page.getByRole('heading', { name: 'Location' })).toBeVisible()
  await page.getByRole('button', { name: 'Continue' }).click()
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page.getByRole('heading', { name: 'Room size' })).toBeVisible()
  await page.getByLabel('Length').fill('0')
  await page.getByLabel('Ceiling height').fill('2')
  await page.getByRole('button', { name: 'Save and continue' }).click()
  await expect(page.getByText('Must be greater than 0')).toBeVisible()
  await expect(page.getByText('Required').first()).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Room size' })).toBeVisible()
})

test('tiny budget is refused with the reason, nothing over budget is saved', async ({ page }) => {
  await signup(page)
  await wizard(page, 'E2E small budget', '3000')
  await page.getByRole('button', { name: 'Create my budget plan' }).click()
  await expect(page.getByText('No plan fits')).toBeVisible()
  await expect(page.getByText(/smallest working system costs about/)).toBeVisible()
  const farmId = page.url().match(/farms\/(\d+)/)![1]
  expect((await (await page.request.get(`/api/farms/${farmId}/designs`)).json())).toEqual([])
})

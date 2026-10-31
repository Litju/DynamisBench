import { expect, test, type Page } from '@playwright/test';

/**
 * Targeted interaction smoke test for the single integrated workbench (RES-575 v0.3 §7).
 * It checks behaviour, not science: the prototype never calls a simulator or backend.
 */

const SHOTS = 'evidence';
const errors: string[] = [];

async function open(page: Page, query = '') {
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  await page.goto(`/workbench${query}`);
  await expect(page.getByTestId('prototype-banner')).toBeVisible();
}

const title = (page: Page) => page.getByTestId('inspector-title');

test('integrated workbench journey', async ({ page }) => {
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 1600, height: 1000 });
  await open(page, '?study=pendulum-qual&mode=lab&sel=joint.hinge&t=0.420');

  // Deep link restores study, selection and time.
  await expect(title(page)).toHaveText('hinge');
  await expect(page.getByTestId('time-readout')).toContainText('t = 0.420 s');
  await page.waitForTimeout(1200);
  await page.screenshot({ path: `${SHOTS}/01-lab-pendulum-1600.png` });

  // 2. Tree selection updates inspector and linked signal highlight.
  await page.locator('[data-node="site.bob"]').click();
  await expect(title(page)).toHaveText('bob');
  await expect(page.getByTestId('plot-bob')).toBeVisible();
  await page.locator('[data-node="body.pendulum"]').click();
  await expect(title(page)).toHaveText('pendulum');

  // Keyboard tree navigation.
  await page.locator('[data-node="body.pendulum"]').focus();
  await page.keyboard.press('ArrowUp');
  await page.keyboard.press('Enter');
  await expect(title(page)).toHaveText('world');

  // 2b. 3D picking: click the hinge pin at the projected origin by probing the canvas.
  const canvas = page.getByTestId('viewport-wrap').locator('canvas');
  const box = (await canvas.boundingBox())!;
  let picked = '';
  for (let y = 0.2; y <= 0.8 && !picked; y += 0.04) {
    for (let x = 0.3; x <= 0.7 && !picked; x += 0.04) {
      await page.mouse.click(box.x + box.width * x, box.y + box.height * y);
      const t = await title(page).textContent();
      if (t && ['pendulum', 'hinge', 'bob', 'world'].includes(t) && t !== 'world') picked = t;
    }
  }
  expect(picked, '3D click selects a model entity').not.toBe('');

  // 3. Orbit / zoom / reset / view presets / overlays.
  await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.5);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.62, box.y + box.height * 0.42, { steps: 8 });
  await page.mouse.up();
  await page.mouse.wheel(0, -300);
  await page.getByRole('button', { name: 'Sagittal (x–z)' }).click();
  await page.getByRole('button', { name: 'Reset view' }).click();
  await page.getByTestId('overlays-btn').click();
  await page.getByLabel('Scene overlays').getByText('Gravity load at COM').click();
  await page.getByTestId('overlays-btn').click();

  // 6. Time scrub synchronises readout, plot cursor and table.
  await page.getByTestId('time-slider').fill('1.25');
  await expect(page.getByTestId('time-readout')).toContainText('t = 1.250 s');
  await expect(page.getByTestId('plot-theta').locator('svg[role="slider"]')).toHaveAttribute('aria-valuenow', '1.25');
  await page.getByTestId('dock-table').click();
  await expect(page.getByTestId('data-table').locator('tr.is-current').first()).toContainText('1.250');
  await page.getByTestId('data-table').locator('tbody tr').nth(51).click(); // 0.500 s row
  await expect(page.getByTestId('time-readout')).toContainText('t = 0.500 s');
  await page.getByTestId('dock-signals').click();
  await page.getByTestId('plot-theta').locator('svg[role="slider"]').focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByTestId('time-readout')).toContainText('t = 0.510 s');

  // Playback advances only the cursor.
  await page.getByTestId('btn-play').click();
  await page.waitForTimeout(500);
  await page.getByTestId('btn-play').click();
  await expect(page.getByTestId('time-readout')).not.toContainText('t = 0.510 s');

  // Phase portrait is linked to the shared cursor.
  await page.getByTestId('plot-phase').locator('svg').click({ position: { x: 60, y: 40 } });
  await expect(page.getByTestId('time-readout')).not.toContainText('t = 0.510 s');

  // Layouts: side dock, scene focus (F / Esc), collapsible panels ([ and ]).
  await page.getByTestId('layout-side').click();
  await expect(page.getByTestId('lab')).toHaveAttribute('data-layout', 'side');
  await page.locator('[data-node="joint.hinge"]').click();
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${SHOTS}/01b-lab-side-layout-1600.png` });
  await page.locator('body').click({ position: { x: 5, y: 5 } });
  await page.keyboard.press('f');
  await expect(page.getByTestId('lab')).toHaveAttribute('data-layout', 'focus');
  await expect(page.getByLabel('Scientific navigator')).toHaveCount(0);
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${SHOTS}/01c-lab-scene-focus-1600.png` });
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('lab')).toHaveAttribute('data-layout', 'side');
  await page.keyboard.press('[');
  await expect(page.getByTestId('rail-left')).toBeVisible();
  await page.getByTestId('rail-left').click();
  await page.getByTestId('layout-bottom').click();

  // 4. Draft scenario change invalidates preflight and is refused; restore → ready.
  await page.locator('[data-node="ctx.scenario"]').click();
  await page.getByTestId('draft-theta0Deg').fill('45');
  await expect(page.getByTestId('draft-diff')).toContainText('1 change');
  await page.getByTestId('btn-preflight').click();
  await expect(page.getByTestId('preflight-decision')).toContainText('REFUSED');
  await expect(page.getByRole('tabpanel')).toContainText('worker_failed');
  await page.screenshot({ path: `${SHOTS}/02-lab-draft-refused-1600.png` });
  await page.getByRole('button', { name: 'Restore reference' }).click();
  await page.getByTestId('btn-preflight').click();
  await expect(page.getByTestId('preflight-decision')).toContainText('READY');

  // 5. Lifecycle: completion, injected failure, timeout, cancellation.
  await page.getByTestId('btn-run').click();
  await expect(page.getByTestId('lifecycle')).toContainText('Process completed', { timeout: 8000 });
  await expect(page.getByTestId('run-log')).toContainText('native evidence: not produced');
  await page.getByTestId('outcome').selectOption('fail');
  await page.getByTestId('btn-run').click();
  await expect(page.getByTestId('lifecycle')).toContainText('Failed', { timeout: 8000 });
  await page.getByTestId('outcome').selectOption('timeout');
  await page.getByTestId('btn-run').click();
  await expect(page.getByTestId('lifecycle')).toContainText('Timed out', { timeout: 8000 });
  await page.getByTestId('outcome').selectOption('complete');
  await page.getByTestId('btn-run').click();
  await expect(page.getByTestId('lifecycle')).toContainText('Running', { timeout: 4000 });
  await page.getByTestId('btn-cancel').click();
  await expect(page.getByTestId('lifecycle')).toContainText('Canceled', { timeout: 4000 });
  await expect(page.getByTestId('run-log')).toContainText('worker_canceled');
  await page.screenshot({ path: `${SHOTS}/03-lab-lifecycle-log-1600.png` });

  // 1. Mode switching preserves study, selection and time (Alt+3 keyboard path).
  await page.locator('[data-node="joint.hinge"]').click();
  await page.getByTestId('time-slider').fill('0.734');
  await page.keyboard.press('Alt+3');
  await expect(page.getByTestId('analysis')).toBeVisible();
  await expect(title(page)).toHaveText('hinge');
  await expect(page).toHaveURL(/mode=analysis/);
  await expect(page).toHaveURL(/t=0\.734/);
  await expect(page.getByTestId('verification')).toContainText('within criterion');
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${SHOTS}/04-analysis-verification-1600.png` });

  // 7. Compare series with alignment, units and tolerance.
  await page.getByTestId('tab-compare').click();
  await expect(page.getByTestId('cmp-verdict')).toContainText('exceeds the stated tolerance');
  await page.getByTestId('cand-series.sie-1ms').check();
  await page.getByTestId('cmp-abstol').fill('0.01');
  await expect(page.getByTestId('cmp-verdict')).toContainText('within the stated tolerance');
  await expect(page.getByTestId('cmp-verdict')).toContainText('not a scientific PASS');
  await page.getByTestId('cand-series.small-angle').check();
  await page.getByTestId('cmp-abstol').fill('1e-8');
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${SHOTS}/05-analysis-compare-1600.png` });

  // 8. Validation and UQ are honest not-assessed interfaces.
  await page.getByTestId('tab-validation').click();
  await expect(page.getByTestId('validation')).toContainText('No experimental reference available');
  await page.getByTestId('tab-uq').click();
  await expect(page.getByTestId('uq')).toContainText('not assessed');

  // 9. Evidence ledger with explicit missing stages.
  await page.getByTestId('mode-evidence').click();
  await page.getByTestId('stage-native').click();
  await expect(page.getByTestId('stage-detail')).toContainText('Nothing in this workbench is sealed');
  await page.getByTestId('stage-source').click();
  await expect(page.getByTestId('stage-detail')).toContainText('eac679a723ccfebb48ea5ee40692fa6ee38f965772b484b94b827be6b9dbfdfd');
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${SHOTS}/06-evidence-1600.png` });

  // Study mode.
  await page.getByTestId('mode-study').click();
  await expect(page.getByTestId('study')).toContainText('Claim ceiling');
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${SHOTS}/07-study-pendulum-1600.png` });

  // 10. Human schematic: design-only, refused, no playback, no fake signals.
  await page.getByLabel('Study', { exact: true }).selectOption('lcmj-sensitivity');
  await page.getByTestId('open-lab').click();
  await expect(page.getByTestId('schematic-banner')).toContainText(/no human physics result/i);
  await expect(page.getByTestId('transport-disabled')).toBeVisible();
  await page.getByTestId('dock-signals').click();
  await expect(page.getByTestId('human-signals')).toContainText('not produced');
  // MyoSim reference model (external, Apache-2.0): real tree, axes and ranges; posing is inspection only.
  await expect(page.getByTestId('schematic-banner')).toContainText('MyoSim reference model');
  await page.locator('[data-node="mbody.tibia_r"]').click();
  await expect(title(page)).toHaveText('tibia_r');
  await expect(page.getByTestId('inspector')).toContainText('External reference model');
  await expect(page.getByTestId('inspector')).toContainText('3.8');
  await page.locator('[data-node="mjoint.knee_angle_r"]').click();
  await expect(page.getByTestId('inspector')).toContainText('2.0944');
  await page.getByTestId('dock-table').click();
  for (const [k, v] of [['hip_flexion_r', '0.9'], ['knee_angle_r', '1.3'], ['ankle_angle_r', '0.35'], ['hip_flexion_l', '0.9'], ['knee_angle_l', '1.3'], ['ankle_angle_l', '0.35']] as const) {
    await page.getByTestId(`myopose-${k}`).fill(v);
  }
  await page.getByTestId('pose-pelvis_tz').fill('0.76');
  await page.getByTestId('pose-pelvis_tilt').fill('0');
  await expect(page.getByTestId('inspector')).toContainText('1.300');
  await page.getByTestId('btn-run').click();
  await expect(page.getByTestId('lifecycle')).toContainText('Refused');
  await expect(page.getByTestId('run-log')).toContainText('unsupported_capability');
  await expect(page.getByTestId('run-log')).toContainText('adapter_engine_mismatch');
  await page.getByTestId('dock-table').click();
  await page.waitForTimeout(2500);
  await page.screenshot({ path: `${SHOTS}/08-lab-human-myosim-1600.png` });
  await page.getByRole('button', { name: 'Sagittal (x–z)' }).click();
  await page.getByTestId('dock-signals').click();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${SHOTS}/08b-lab-human-myosim-sagittal-1600.png` });
  // Design-only schematic remains available for comparison.
  await page.getByTestId('geo-schematic').click();
  await expect(page.getByTestId('schematic-banner')).toContainText('representative schematic');
  await page.getByTestId('geo-myosim').click();
  await page.getByTestId('mode-analysis').click();
  await page.getByTestId('tab-validation').click();
  await expect(page.getByTestId('validation')).toContainText('no measured data is present');
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${SHOTS}/09-analysis-human-validation-1600.png` });
  await page.getByTestId('tab-uq').click();
  await page.getByTestId('uq-levels').fill('5');
  await expect(page.getByTestId('uq')).toContainText('15');
  await page.getByTestId('mode-study').click();
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${SHOTS}/10-study-lcmj-fixture-1600.png` });

  // Dark theme for long sessions.
  await page.getByTestId('theme-btn').click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await page.getByTestId('mode-lab').click();
  await page.locator('[data-node="mjoint.knee_angle_r"]').click();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${SHOTS}/13-dark-lab-human-1600.png` });
  await page.getByLabel('Study', { exact: true }).selectOption('pendulum-qual');
  await page.getByTestId('mode-analysis').click();
  await page.getByTestId('tab-compare').click();
  await page.waitForTimeout(900);
  await page.screenshot({ path: `${SHOTS}/14-dark-analysis-compare-1600.png` });
  await page.getByTestId('legend-btn').click();
  await expect(page.getByRole('dialog', { name: 'Data source legend' })).toContainText('Prototype computation');
  await page.getByTestId('theme-btn').click();

  expect(errors, errors.join('\n')).toEqual([]);
});

test('desktop and narrow sizes render without document overflow', async ({ page }) => {
  for (const [w, h, name] of [[1280, 800, '1280'], [1024, 768, '1024']] as const) {
    await page.setViewportSize({ width: w, height: h });
    await open(page, '?study=pendulum-qual&mode=lab&sel=joint.hinge&t=0.300');
    await page.waitForTimeout(1200);
    await page.screenshot({ path: `${SHOTS}/11-lab-${name}.png` });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, `horizontal overflow at ${w}px`).toBeLessThanOrEqual(0);
  }
  await page.setViewportSize({ width: 1280, height: 800 });
  await open(page, '?study=pendulum-qual&mode=analysis&tab=compare&sel=joint.hinge&t=1.000');
  await page.waitForTimeout(1000);
  await page.screenshot({ path: `${SHOTS}/12-analysis-compare-1280.png` });
  expect(errors).toEqual([]);
});

'use strict';
function syncPayment(form) {
  const mode = form.elements.payment_mode?.value;
  if (mode) {
    form.querySelector('[data-split]').hidden = mode !== 'split';
    form.querySelector('[data-bank]').hidden = !['split', 'bank'].includes(mode);
  }
  if (form.dataset.kind === 'sale') {
    const total = [...form.querySelectorAll('[name=cash], [name=split_bank_amount], [name=split_credit_amount]')]
      .reduce((sum, input) => sum + Number(input.value), 0);
    form.querySelector('output').textContent = total ? 'Total sales · NPR ' + total.toFixed(2) : '';
  }
  const account = form.elements.bank_id;
  if (account && !account.value && !account.closest('[hidden]') && account.options.length === 2) {
    account.selectedIndex = 1;
  }
}

function syncBankChoices(form) {
  const banks = [...form.querySelectorAll('[name=split_bank_id]')];
  const selected = new Set(banks.map(bank => bank.value));
  for (const bank of banks) {
    for (const option of bank.options) {
      option.disabled = Boolean(option.value && option.value !== bank.value && selected.has(option.value));
    }
  }
}

function syncItem(input) {
  const row = input.closest('.line');
  const item = Array.from(document.getElementById('items').options).find(
    option => option.value.toLowerCase() === input.value.trim().toLowerCase()
  );
  const category = row.querySelector('[name=row_category]');
  const unit = row.querySelector('[name=row_unit]');
  const toggle = row.querySelector('[data-quantity]');
  if (item) {
    input.value = item.value;
    category.value = item.dataset.category;
    unit.value = item.dataset.unit;
    if (item.dataset.tracked === '1') toggle.checked = true;
    row.dataset.catalogueItem = item.value;
  } else if (row.dataset.catalogueItem) {
    category.value = '';
    unit.value = '';
    delete row.dataset.catalogueItem;
  }
  row.querySelector('.quantity').hidden = !toggle.checked;
}

let itemInput;

function filterItems(picker) {
  const terms = picker.querySelector('[data-item-search]').value.toLowerCase().trim().split(/\s+/);
  const category = picker.querySelector('select').value.toLowerCase();
  let match = false;
  for (const choice of picker.querySelectorAll('[data-item-name]')) {
    const text = choice.textContent.toLowerCase();
    choice.hidden = Boolean(category && choice.dataset.itemCategory.toLowerCase() !== category)
      || !terms.every(term => text.includes(term));
    match ||= !choice.hidden;
  }
  picker.querySelector('[data-item-empty]').hidden = match;
}

function browseItems(input) {
  const picker = document.getElementById('item-picker');
  itemInput = input;
  const manual = picker.querySelector('[data-custom-item]');
  if (manual) manual.hidden = input.form.dataset.kind !== 'bill';
  picker.querySelector('[data-item-search]').value = '';
  picker.querySelector('select').value = '';
  filterItems(picker);
  picker.showModal();
}

function syncVariants(rows) {
  const multiple = rows.children.length > 1;
  for (const row of rows.children) {
    row.querySelector('[name=variant_variation]').required = multiple;
    row.querySelector('[data-remove-variant]').hidden = !multiple;
  }
}

function syncCashCount(form) {
  const expected = form.elements.counter_id.selectedOptions[0]?.dataset.expected;
  const actual = form.elements.actual;
  const variance = expected !== undefined && actual.value !== ''
    ? Math.round(actual.valueAsNumber * 100) - Math.round(Number(expected) * 100)
    : 0;
  form.elements.reason.required = Boolean(variance);
  form.querySelector('[data-cash-variance]').textContent = expected === undefined ? ''
    : 'Expected cash · NPR ' + expected + (variance ? ' · Variance · NPR ' + (variance / 100).toFixed(2) : '');
}

function applyTheme(theme) {
  const selected = ['light', 'dark', 'hybrid'].includes(theme) ? theme : 'hybrid';
  document.documentElement.dataset.theme = selected;
  const picker = document.querySelector('[data-theme-picker]');
  if (picker) picker.value = selected;
}
applyTheme(localStorage.getItem('rms-theme'));

function openRequestedForm() {
  applyTheme(document.documentElement.dataset.theme);
  const dialog = document.querySelector('dialog[data-open]:not([open])');
  if (dialog) {
    dialog.removeAttribute('data-open');
    dialog.showModal();
    if (dialog.id === "entry-settle_counter") syncCashCount(dialog.querySelector("form"));
  }
  document.querySelectorAll('form[data-kind="sale"], form[data-kind="bill"]').forEach(syncPayment);
}

document.addEventListener('DOMContentLoaded', openRequestedForm);
document.addEventListener('htmx:afterSwap', openRequestedForm);
window.addEventListener('pageshow', () => {
  document.querySelectorAll('form[data-kind="sale"], form[data-kind="bill"]').forEach(syncPayment);
});

document.addEventListener('change', event => {
  const input = event.target, form = input.form;
  if (input.matches('[data-theme-picker]')) {
    applyTheme(input.value);
    localStorage.setItem('rms-theme', input.value);
  }
  if (input.matches('[data-auto]')) form.requestSubmit();
  if (input.matches('[data-period]')) {
    form.querySelector('[data-range]').hidden = input.value !== 'custom';
    if (input.value !== 'custom') form.requestSubmit();
  }
  if (input.name === 'payment_mode') syncPayment(form);
  if (input.name === 'split_bank_id') syncBankChoices(form);
  if (input.name === 'credit_type') {
    form.elements.party.setAttribute('list', input.value === 'payable' ? 'supplier-names' : 'customer-names');
  }
  if (input.getAttribute('list') === 'stockitems') {
    const item = [...input.list.options].find(option => option.value.toLowerCase() === input.value.trim().toLowerCase());
    const unit = form.querySelector('[data-stock-unit]');
    if (unit) unit.textContent = item ? 'Base unit · ' + item.dataset.unit : '';
  }
  if (input.matches('[data-quantity]')) input.closest('.line').querySelector('.quantity').hidden = !input.checked;
  if (input.name === 'row_name' && form.dataset.kind === 'bill') syncItem(input);
  if (input.matches('select[data-item-category]')) filterItems(input.closest('dialog'));
  if (form?.dataset.kind === 'handover' && input.name === 'counter_id') syncCashCount(form);
});
document.addEventListener('input', event => {
  if (event.target.matches('[data-item-search]')) filterItems(event.target.closest('dialog'));
  if (event.target.name === 'actual' && event.target.form?.dataset.kind === 'handover') {
    syncCashCount(event.target.form);
  }
  if (event.target.name === 'split_bank_amount' && Number(event.target.value) > 0) {
    const bank = event.target.closest('.allocation-row').querySelector('select');
    if (!bank.value && bank.options.length === 2 && !bank.options[1].disabled) {
      bank.selectedIndex = 1;
      syncBankChoices(bank.form);
    }
  }
  if (event.target.form?.dataset.kind === 'sale' && event.target.type === 'number') {
    syncPayment(event.target.form);
  }
});
document.addEventListener('click', event => {
  if (event.target.matches('[data-item-input]')) browseItems(event.target);
  const b = event.target.closest('button');
  if (!b) return;
  if (b.hasAttribute('data-browse-items')) browseItems(b.parentElement.querySelector('[data-item-input], [data-stock-picker]'));
  if (b.hasAttribute('data-item-name') || b.hasAttribute('data-custom-item')) {
    if (b.hasAttribute('data-item-name')) {
      itemInput.value = b.dataset.itemName;
      itemInput.dispatchEvent(new Event('change', {bubbles: true}));
    }
    b.closest('dialog').close();
    itemInput.focus();
    if (b.hasAttribute('data-custom-item')) itemInput.select();
  }
  if (b.hasAttribute('data-add-variant')) {
    const rows = b.form.querySelector('[data-variant-rows]');
    rows.append(b.form.querySelector('[data-variant-template]').content.cloneNode(true));
    syncVariants(rows);
    rows.lastElementChild.querySelector('input').focus();
  }
  if (b.hasAttribute('data-remove-variant')) {
    const row = b.closest('[data-variant-row]');
    const rows = row.parentElement;
    b.form.querySelector('[data-add-variant]').focus();
    row.remove();
    syncVariants(rows);
  }
  if (b.hasAttribute('data-add-allocation')) {
    const section = b.closest('[data-allocation]');
    const rows = section.querySelector('[data-allocation-rows]');
    rows.append(section.querySelector('template').content.cloneNode(true));
    syncBankChoices(b.form);
    rows.lastElementChild.querySelector('select, input').focus();
  }
  if (b.hasAttribute('data-remove-allocation')) {
    const section = b.closest('[data-allocation]');
    b.closest('.allocation-row').remove();
    section.querySelector('[data-add-allocation]').focus();
    syncBankChoices(section.closest('form'));
    syncPayment(section.closest('form'));
  }
  if (b.hasAttribute('data-add')) {
    const lines = b.form.querySelector('.lines');
    lines.append(b.form.querySelector('template[data-item-row]').content.cloneNode(true));
    lines.lastElementChild.querySelector('[name=row_name]').focus();
  }
  if (b.hasAttribute('data-remove')) {
    const form = b.form;
    b.closest('.line').remove();
    form.querySelector('[data-add]').focus();
  }
  if (b.dataset.dialog) {
    const dialog = document.getElementById(b.dataset.dialog);
    if (b.dataset.counter) dialog.querySelector('[name=counter_id]').value = b.dataset.counter;
    dialog.showModal();
    if (dialog.id === 'entry-settle_counter') syncCashCount(dialog.querySelector('form'));
  }
  if (b.hasAttribute('data-dismiss')) b.closest('dialog').close();
  if (b.dataset.settle) {
    const modal = document.getElementById('settle');
    modal.querySelector('[name=origin]').value = b.dataset.settle;
    modal.querySelector('[name=amount]').max = b.dataset.balance;
    modal.showModal();
  }
  if (b.hasAttribute('data-print')) window.print();
});
document.addEventListener('submit', async event => {
  const form = event.target;
  if (!form.classList.contains('entryform')) return;
  event.preventDefault();
  if (form.dataset.busy) return;
  form.dataset.busy = '1';
  const button = form.querySelector('[type=submit],button.primary,button.danger');
  button.disabled = true;
  let alert = form.querySelector('[role=alert]');
  if (!alert) { alert=document.createElement('p'); alert.setAttribute('role','alert'); form.append(alert); }
  alert.hidden=true;
  try {
    const fields=new FormData(form);
    const qty=Array.from(form.querySelectorAll('.line'));
    if (form.dataset.kind==='bill') {
      fields.delete('row_qty'); fields.delete('row_unit');
      for (const row of qty) {
        const enabled=row.querySelector('[data-quantity]').checked;
        fields.append('row_qty',enabled?row.querySelector('[name=row_qty]').value:'');
        fields.append('row_unit',enabled?row.querySelector('[name=row_unit]').value:'');
      }
    }
    const response=await fetch(form.getAttribute('action'),{method:'POST',body:fields,headers:{Accept:'application/json'}});
    if (response.redirected) { location.assign(response.url); return; }
    if (response.ok) { const saved=await response.json(); location.assign(saved.location); return; }
    const doc=new DOMParser().parseFromString(await response.text(),'text/html');
    alert.textContent=doc.querySelector('[role=alert]')?.textContent || 'Could not save. Reload if your session expired.';
  } catch { alert.textContent='Connection interrupted. Retry this same form to check whether it was saved.'; }
  alert.hidden = false;
  alert.tabIndex = -1;
  alert.focus();
  button.disabled = false;
  delete form.dataset.busy;
});
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(()=>{});

function initTablePagination() {
  for (const wrap of document.querySelectorAll('[data-paginate]:not([data-paginated])')) {
    wrap.dataset.paginated = '';
    const rows = [...wrap.querySelectorAll('table tr')].filter(row => row.cells[0]?.tagName === 'TD');
    const pageSize = 20;
    if (rows.length <= pageSize) continue;
    const totalPages = Math.ceil(rows.length / pageSize);
    const pager = document.createElement('div');
    pager.className = 'toolbar table-pager';
    pager.innerHTML = '<button type="button" class="btn tiny">Previous</button>'
      + '<span aria-live="polite"></span><button type="button" class="btn tiny">Next</button>';
    const [previous, status, next] = pager.children;
    let page = 0;

    function render() {
      rows.forEach((row, index) => { row.hidden = Math.floor(index / pageSize) !== page; });
      previous.disabled = page === 0;
      next.disabled = page === totalPages - 1;
      status.textContent = 'Page ' + (page + 1) + ' of ' + totalPages;
    }

    previous.addEventListener('click', () => { page -= 1; render(); });
    next.addEventListener('click', () => { page += 1; render(); });
    wrap.after(pager);
    render();
    // Keep all rows available to the print stylesheet.
    for (const row of rows) row.classList.add('paginated-row');
  }
}

function initOverviewChart() {
  const panel = document.querySelector('[data-chart]:not([data-chart-ready])');
  if (!panel) return;
  panel.dataset.chartReady = '';
  const canvas = panel.querySelector('canvas');
  const context = canvas.getContext('2d');
  const tooltip = panel.querySelector('.chart-tooltip');
  const points = JSON.parse(panel.dataset.points);
  const type = panel.dataset.chartType;
  const keys = ['sales', 'expenses'].filter(key => panel.dataset.chartSeries === 'both' || key === panel.dataset.chartSeries);
  const colors = {sales: '#268365', expenses: '#bf773d'};
  const labels = {sales: 'Sales', expenses: 'Expenses'};
  const money = new Intl.NumberFormat(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
  const totals = keys.map(key => points.reduce((sum, point) => sum + Number(point[key]), 0));
  const total = totals.reduce((sum, amount) => sum + amount, 0);
  const limit = Math.max(1, ...points.flatMap(point => keys.map(key => Number(point[key]))));
  let active = -1;
  let plot;

  function draw() {
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (!width || !height) return;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    const color = getComputedStyle(panel).color;
    const dark = document.documentElement.dataset.theme === 'dark';
    context.font = '11px system-ui';
    context.fillStyle = color;
    if (type === 'donut') {
      const radius = Math.min(width, height) * .40;
      plot = {cx: width / 2, cy: height / 2, radius};
      let start = -Math.PI / 2;
      totals.forEach((amount, index) => {
        if (!total || !amount) return;
        const end = start + 2 * Math.PI * amount / total;
        context.beginPath();
        context.arc(plot.cx, plot.cy, radius * .80, start, end);
        context.strokeStyle = colors[keys[index]];
        context.globalAlpha = active < 0 || active === index ? 1 : .42;
        context.lineWidth = radius * .38;
        context.stroke();
        start = end;
      });
      context.globalAlpha = 1;
      context.fillStyle = color;
      context.textAlign = 'center';
      context.fillText(total ? 'NPR ' + money.format(total) : 'No activity', plot.cx, plot.cy + 4);
      return;
    }

    const tickFormat = new Intl.NumberFormat(undefined, {notation: 'compact', maximumFractionDigits: 1});
    const x = 48, top = 14, bottom = height - 29;
    const step = (width - x - 12) / points.length;
    const pointX = index => x + (index + .5) * step;
    const pointY = amount => bottom - (amount / limit) * (bottom - top);
    plot = {x, step};
    context.textAlign = 'right';
    context.lineWidth = 1;
    for (let tick = 0; tick <= 4; tick += 1) {
      const amount = limit * tick / 4;
      const y = pointY(amount);
      context.fillText(tickFormat.format(amount), x - 7, y + 4);
      context.strokeStyle = dark ? '#496055' : '#dce6df';
      context.beginPath();
      context.moveTo(x, y);
      context.lineTo(width - 10, y);
      context.stroke();
    }
    if (active >= 0) {
      context.fillStyle = dark ? '#3d5c50' : '#eaf3ee';
      context.fillRect(x + active * step, top, step, bottom - top);
    }
    context.textAlign = 'center';
    context.fillStyle = color;
    const labelStep = Math.max(1, Math.ceil(points.length / Math.max(2, Math.floor((width - x) / 53))));
    points.forEach((point, index) => {
      if (index % labelStep === 0) context.fillText(point.label, pointX(index), height - 9);
    });
    keys.forEach((key, keyIndex) => {
      context.fillStyle = context.strokeStyle = colors[key];
      if (type === 'line') {
        context.lineWidth = 2.5;
        context.beginPath();
        points.forEach((point, index) => context.lineTo(pointX(index), pointY(Number(point[key]))));
        context.stroke();
        points.forEach((point, index) => {
          context.beginPath();
          context.arc(pointX(index), pointY(Number(point[key])), index === active ? 5 : 2.5, 0, 2 * Math.PI);
          context.fill();
        });
      } else {
        const bar = Math.min(24, step * .68 / keys.length);
        points.forEach((point, index) => {
          const y = pointY(Number(point[key]));
          context.fillRect(pointX(index) + (keyIndex - keys.length / 2) * bar + 1, y, Math.max(1, bar - 2), bottom - y);
        });
      }
    });
  }

  function inspect(index) {
    if (index === active) return;
    active = index;
    tooltip.hidden = index < 0;
    if (index >= 0) {
      tooltip.textContent = type === 'donut'
        ? labels[keys[index]] + ' · NPR ' + money.format(totals[index])
        : points[index].label + ' · ' + keys.map(key => labels[key] + ' NPR ' + money.format(Number(points[index][key]))).join(' · ');
    }
    draw();
  }

  canvas.addEventListener('pointermove', event => {
    if (!plot) return;
    if (type !== 'donut') {
      const index = Math.floor((event.offsetX - plot.x) / plot.step);
      inspect(index >= 0 && index < points.length ? index : -1);
      return;
    }
    const dx = event.offsetX - plot.cx, dy = event.offsetY - plot.cy;
    const distance = Math.hypot(dx, dy);
    if (!total || distance < plot.radius * .60 || distance > plot.radius) { inspect(-1); return; }
    const angle = (Math.atan2(dy, dx) + Math.PI / 2 + 2 * Math.PI) % (2 * Math.PI);
    let end = 0;
    inspect(totals.findIndex(amount => {
      end += 2 * Math.PI * amount / total;
      return angle < end;
    }));
  });
  canvas.addEventListener('pointerleave', () => inspect(-1));
  canvas.addEventListener('blur', () => inspect(-1));
  canvas.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
    event.preventDefault();
    const last = (type === 'donut' ? keys.length : points.length) - 1;
    inspect(Math.min(last, Math.max(0, active + (event.key === 'ArrowRight' ? 1 : -1))));
  });
  const resize = new ResizeObserver(() => {
    if (canvas.isConnected) draw();
    else resize.disconnect();
  });
  resize.observe(canvas);
  const themes = new MutationObserver(() => {
    if (canvas.isConnected) draw();
    else themes.disconnect();
  });
  themes.observe(document.documentElement, {attributeFilter: ['data-theme']});
  draw();
}

for (const event of ['DOMContentLoaded', 'htmx:afterSwap']) {
  document.addEventListener(event, () => {
    initTablePagination();
    initOverviewChart();
  });
}

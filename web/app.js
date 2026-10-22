(() => {
  const $ = (selector) => document.querySelector(selector);
  const state = { erpFile: null, inventoryFiles: [], result: null, busy: false };
  const stores = [
    { value: 'DEMOA_US_US', label: 'DEMOA' },
    { value: 'DEMOC_US', label: 'DEMOC' },
    { value: 'DEMOB_US', label: 'DEMOB' },
    { value: 'DEMOD_US', label: 'DEMOD' },
  ];
  let toastTimer;

  const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
  })[char]);
  const num = (value) => value === null || value === undefined || value === ''
    ? '?'
    : Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 });
  const statusLabel = (status) => status === 'manual' ? '人工处理' : '可放行';
  const storeLabel = (value) => stores.find((item) => item.value === value)?.label || value || '未知店铺';
  const detectStore = (filename) => {
    const upper = String(filename || '').toUpperCase();
    if (upper.includes('DEMOA')) return 'DEMOA_US_US';
    if (upper.includes('DEMOC')) return 'DEMOC_US';
    if (upper.includes('DEMOB')) return 'DEMOB_US';
    if (upper.includes('DEMOD')) return 'DEMOD_US';
    return '';
  };
  const toast = (message) => {
    const node = $('#toast');
    node.textContent = message;
    node.classList.add('is-visible');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => node.classList.remove('is-visible'), 2800);
  };
  const ready = () => Boolean(state.erpFile && state.inventoryFiles.length && state.inventoryFiles.every((file) => file.seller));
  const updateReady = () => {
    const canStart = ready();
    $('#audit-button').disabled = state.busy || !canStart;
    $('#upload-state').textContent = canStart ? '文件已就绪' : state.inventoryFiles.length ? '请完成匹配' : '等待文件';
    $('#upload-state').classList.toggle('is-ready', canStart);
    const fileHint = state.erpFile && state.inventoryFiles.length
      ? '文件已准备'
      : state.erpFile ? '还需库存文件' : state.inventoryFiles.length ? '还需 ERP 文件' : '等待文件';
    if ($('#rail-file-count')) $('#rail-file-count').textContent = fileHint;
  };
  const renderFiles = () => {
    $('#erp-file-label').textContent = state.erpFile ? state.erpFile.name : '未选择文件';
    const list = $('#file-list');
    if (!state.inventoryFiles.length) {
      list.innerHTML = '<div class="file-row file-row-empty"><span class="file-name">还没有库存文件</span><span class="map-status is-unknown">待加入</span></div>';
      updateReady();
      return;
    }
    list.innerHTML = state.inventoryFiles.map((file, index) => {
      const options = ['<option value="">请手动匹配</option>']
        .concat(stores.map((store) => `<option value="${store.value}" ${store.value === file.seller ? 'selected' : ''}>${store.label}</option>`))
        .join('');
      return `<div class="file-row">
        <span class="file-name" title="${esc(file.name)}">${esc(file.name)}</span>
        <span class="file-map"><span class="map-status ${file.seller ? '' : 'is-unknown'}">${file.seller ? '已识别' : '需匹配'}</span>
        <select data-map-index="${index}" aria-label="${esc(file.name)} 店铺匹配">${options}</select></span>
      </div>`;
    }).join('');
    list.querySelectorAll('[data-map-index]').forEach((select) => select.addEventListener('change', (event) => {
      state.inventoryFiles[Number(event.target.dataset.mapIndex)].seller = event.target.value;
      renderFiles();
    }));
    updateReady();
  };
  const normalized = (order) => [
    order.order_no, order.seller, order.buyer_id,
    ...(order.reasons || []),
    ...(order.lines || []).flatMap((line) => [line.platform_sku, line.warehouse_sku]),
  ].join(' ').toLowerCase();
  const matches = (order) => {
    const search = $('#search-input').value.trim().toLowerCase();
    const store = $('#store-filter').value;
    const reason = $('#reason-filter').value;
    const presale = $('#presale-filter').value;
    return (!search || normalized(order).includes(search))
      && (!store || order.seller === store)
      && (!reason || (order.reasons || []).includes(reason))
      && (!presale || (presale === 'presale' ? order.is_presale === true : order.is_presale !== true));
  };
  const evidencePill = (label, value) => `<span class="evidence-pill"><small>${label}</small><strong>${value}</strong></span>`;
  const reasonList = (order, manual) => {
    const reasons = order.reasons || [];
    if (!manual) return '<ul class="reason-list pass-reasons"><li>规则全部通过，可直接放行</li></ul>';
    return `<ul class="reason-list">${(reasons.length ? reasons : ['需要人工复核']).map((reason) => `<li>${esc(reason)}</li>`).join('')}</ul>`;
  };
  const lineEvidence = (line) => {
    const evidence = line.evidence || {};
    const lineReasons = line.reasons || [];
    return `<div class="evidence-row">
      <div class="sku-identity">
        <div class="sku-identity-field sku-identity-platform"><span>平台 SKU</span><strong data-copy-sku="${esc(line.platform_sku || '未提供')}" role="button" tabindex="0" title="点击复制 SKU">${esc(line.platform_sku || '未提供')}</strong></div>
        <div class="sku-identity-field sku-identity-warehouse"><span>云仓 SKU</span><strong data-copy-sku="${esc(line.warehouse_sku || '未提供')}" role="button" tabindex="0" title="点击复制 SKU">${esc(line.warehouse_sku || '未提供')}</strong></div>
      </div>
      <div class="evidence-grid">
        ${evidencePill('需求', num(evidence.demand))}
        ${evidencePill('购买数', num(line.qty))}
        ${evidencePill('圈买库存', num(evidence.circle_stock))}
        ${evidencePill('分销库存', num(evidence.distribution_stock))}
        ${evidencePill('成本价', num(evidence.cost_price))}
        ${evidencePill('优惠价', num(evidence.discount_price))}
      </div>
      ${lineReasons.length ? `<div class="line-reason-note">本商品命中：${lineReasons.map((reason) => `<span>${esc(reason)}</span>`).join('')}</div>` : ''}
    </div>`;
  };
  const card = (order) => {
    const manual = order.status === 'manual';
    const lines = order.lines || [];
    const reasons = order.reasons || [];
    const skuSummary = lines.map((line) => `<span class="summary-sku-line">
      <span class="summary-sku-field"><span class="summary-sku-label">平台 SKU</span><strong class="summary-sku-platform" data-copy-sku="${esc(line.platform_sku || '未提供')}" role="button" tabindex="0" title="点击复制 SKU">${esc(line.platform_sku || '未提供')}</strong></span>
      <span class="summary-sku-field"><span class="summary-sku-label">云仓 SKU</span><strong class="summary-sku-warehouse" data-copy-sku="${esc(line.warehouse_sku || '未提供')}" role="button" tabindex="0" title="点击复制 SKU">${esc(line.warehouse_sku || '未提供')}</strong></span>
      <span class="summary-sku-qty">× ${num(line.qty)}</span>
    </span>`).join('');
    const reasonPreview = manual
      ? reasons.slice(0, 2).map((reason) => `<span class="reason-tag">${esc(reason)}</span>`).join('')
      : '<span class="reason-tag reason-tag-pass">规则全部通过</span>';
    return `<details class="order-card ${manual ? 'manual-card' : 'pass-card'}" data-order-no="${esc(order.order_no)}">
      <summary class="order-summary">
        <span class="status-rail" aria-hidden="true"></span>
        <span class="order-summary-main">
          <span class="order-topline"><button class="order-number copy-order-number" type="button" data-copy-order="${esc(order.order_no)}" title="\u70b9\u51fb\u590d\u5236\u8ba2\u5355\u53f7">${esc(order.order_no)}</button><span class="order-store">${esc(storeLabel(order.seller))}</span>${order.is_presale ? '<span class="order-presale">\u9884\u552e</span>' : ''}</span>
          <span class="order-meta"><span>buyer_id <b>${esc(order.buyer_id || '?')}</b></span><span>${lines.length} 个商品明细</span><span class="detail-status ${manual ? 'manual' : 'pass'}">${statusLabel(order.status)}</span></span>
          <span class="reason-preview">${reasonPreview}</span>
          <span class="order-footer"><span class="expand-hint"><span class="expand-hint-text">${manual ? '向上展开详情' : '展开查看证据'}</span><span class="expand-arrow" aria-hidden="true">⌄</span></span></span>
          <span class="summary-skus">${skuSummary || '<span class="summary-sku-label">无商品明细</span>'}</span>
        </span>
      </summary>
      <div class="order-detail">
        <div class="detail-heading"><div><p class="eyebrow">REVIEW NOTES</p><h4>${manual ? '为什么需要人工处理' : '放行依据'}</h4></div><span class="detail-count">${manual ? reasons.length : 0} 条原因</span></div>
        ${order.date_latest_ship ? `<div class="ship-date-note"><span>最晚发货日期</span><strong>${esc(order.date_latest_ship)}</strong>${order.latest_ship_age_days === null || order.latest_ship_age_days === undefined ? '' : `<em>距最晚发货还有 ${num(order.latest_ship_age_days)} 天</em>`}</div>` : ''}
        ${reasonList(order, manual)}
        <div class="detail-block"><div class="detail-heading"><div><p class="eyebrow">EVIDENCE</p><h4>库存与价格证据</h4></div><span class="detail-count">${lines.length} 个商品</span></div>${lines.length ? lines.map(lineEvidence).join('') : '<p class="detail-empty">没有可展示的商品明细。</p>'}</div>
        ${order.duplicate_orders?.length ? `<div class="duplicate-note"><strong>关联重复订单</strong><span>${order.duplicate_orders.map((item) => esc(item)).join(' · ')}</span></div>` : ''}
      </div>
    </details>`;
  };
  const attachOrderInteractions = (container) => {
    container.onclick = (event) => {
      const copyButton = event.target.closest('[data-copy-order], [data-copy-sku]');
      if (copyButton) {
        event.preventDefault();
        event.stopPropagation();
        copyText(copyButton.dataset.copySku ?? copyButton.dataset.copyOrder, copyButton.dataset.copySku !== undefined ? '\u5df2\u590d\u5236 SKU' : '\u5df2\u590d\u5236\u8ba2\u5355\u53f7');
        return;
      }
      const summary = event.target.closest('summary.order-summary');
      if (!summary) return;
      event.preventDefault();
      const current = summary.closest('.order-card');
      const manual = current.classList.contains('manual-card');
      const anchorTop = summary.getBoundingClientRect().top;
      const expanded = !current.open;
      const setExpanded = (item, open) => {
        item.open = open;
        item.querySelector('.expand-hint-text').textContent = open
          ? '收起详情'
          : (item.classList.contains('manual-card') ? '向上展开详情' : '展开查看证据');
      };
      container.querySelectorAll('.order-card[open]').forEach((other) => { if (other !== current) setExpanded(other, false); });
      setExpanded(current, expanded);
      if (manual) {
        // Keep the summary and next order in place as evidence opens above it.
        const offset = summary.getBoundingClientRect().top - anchorTop;
        window.scrollBy({ top: offset, behavior: 'instant' });
      }
    };
    container.onkeydown = (event) => {
      const copySku = event.target.closest('[data-copy-sku]');
      if (!copySku || (event.key !== 'Enter' && event.key !== ' ')) return;
      event.preventDefault();
      event.stopPropagation();
      copyText(copySku.dataset.copySku, '\u5df2\u590d\u5236 SKU');
    };
  };

  const renderResults = () => {
    const result = state.result;
    if (!result) return;
    const summary = result.summary || {};
    const orders = result.orders || [];
    const selectedStore = $('#store-filter').value;
    const selectedReason = $('#reason-filter').value;
    const selectedPresale = $('#presale-filter').value;
    $('#kpi-total').textContent = summary.total_orders || 0;
    $('#kpi-manual').textContent = summary.manual_orders || 0;
    $('#kpi-pass').textContent = summary.pass_orders || 0;
    $('#kpi-sku').textContent = Object.keys(result.sku_groups || {}).length;
    $('#rail-manual-count').textContent = `${summary.manual_orders || 0} 个订单待处理`;
    $('#rail-pass-count').textContent = `${summary.pass_orders || 0} 个订单可放行`;
    $('#manual-section-count').textContent = summary.manual_orders || 0;
    $('#pass-section-count').textContent = summary.pass_orders || 0;
    const resultStores = [...new Set(orders.map((order) => order.seller).filter(Boolean))];
    $('#store-filter').innerHTML = '<option value="">全部店铺</option>' + resultStores.map((store) => `<option value="${esc(store)}">${esc(storeLabel(store))}</option>`).join('');
    const reasons = [...new Set(orders.flatMap((order) => order.reasons || []))].sort();
    $('#reason-filter').innerHTML = '<option value="">全部原因</option>' + reasons.map((reason) => `<option value="${esc(reason)}">${esc(reason)}</option>`).join('');
    $('#store-filter').value = selectedStore;
    $('#reason-filter').value = selectedReason;
    $('#presale-filter').value = selectedPresale;
    const visible = orders.filter(matches);
    const manual = visible.filter((order) => order.status === 'manual');
    const pass = visible.filter((order) => order.status === 'pass');
    $('#manual-list').innerHTML = manual.map(card).join('');
    $('#manual-empty').hidden = manual.length > 0;
    $('#pass-orders').innerHTML = pass.map(card).join('');
    attachOrderInteractions($('#manual-list'));
    attachOrderInteractions($('#pass-orders'));
    $('#copy-button').disabled = !(summary.manual_orders > 0);
    $('#export-button').classList.toggle('is-disabled', !result.run_id);
    $('#export-button').href = result.run_id ? `/api/export/${result.run_id}` : '#';
  };
  const auditFiles = async () => {
    if (!ready()) { toast('请先上传文件并完成店铺匹配'); return; }
    state.busy = true;
    document.body.classList.add('busy');
    updateReady();
    $('#audit-button').innerHTML = '正在审单 <span aria-hidden="true">→</span>';
    try {
      const form = new FormData();
      form.append('erp', state.erpFile, state.erpFile.name);
      const mapping = {};
      state.inventoryFiles.forEach((file) => { form.append('inventory', file.file, file.name); mapping[file.name] = file.seller; });
      form.append('inventory_mapping', JSON.stringify(mapping));
      const response = await fetch('/api/audit', { method: 'POST', body: form });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error?.message || '审单失败');
      state.result = payload;
      renderResults();
      toast(`审单完成：${payload.summary.manual_orders} 个订单需要人工处理`);
      $('#results').scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (error) {
      toast(error.message || '审单失败');
    } finally {
      state.busy = false;
      document.body.classList.remove('busy');
      updateReady();
      $('#audit-button').innerHTML = '开始审单 <span aria-hidden="true">→</span>';
    }
  };
  const demo = () => {
    state.result = {
      run_id: null,
      summary: { total_orders: 5, manual_orders: 3, pass_orders: 2, total_lines: 6, manual_lines: 3 },
      sku_groups: { 'WH-CHAIR-01': { demand: 2 }, 'WH-SOFA-02': { demand: 1 }, 'WH-LAMP-03': { demand: 1 } },
      orders: [
        { order_no: '114-0000000-0000025', seller: 'DEMOD_US', buyer_id: 'demo_buyer_a', status: 'manual', reasons: ['圈买库存不足', '成本价与分销优惠价差异超过 3'], lines: [{ platform_sku: 'W3434P080023-ZE-HR', warehouse_sku: 'W3434P080023', qty: 1, reasons: ['圈买库存不足', '成本价与分销优惠价差异超过 3'], evidence: { demand: 4, circle_stock: 0, distribution_stock: 2, cost_price: 28, discount_price: 33 } }] },
        { order_no: '112-0000000-0000017', seller: 'DEMOC_US', buyer_id: 'demo_buyer_b', status: 'manual', reasons: ['单个订单购买数量 ≥ 2'], lines: [{ platform_sku: 'W2339S80021-VY-HR', warehouse_sku: 'W2339S80021', qty: 2, reasons: ['单个订单购买数量 ≥ 2'], evidence: { demand: 2, circle_stock: 10, distribution_stock: 0, cost_price: 90, discount_price: 90 } }] },
        { order_no: '112-0000000-0000009', seller: 'DEMOB_US', buyer_id: 'demo_buyer_c', status: 'manual', reasons: ['同一用户重复购买'], duplicate_orders: ['112-0000000-0000010'], lines: [{ platform_sku: 'W1359S80007-XO-TL', warehouse_sku: 'W1359S80008', qty: 1, reasons: ['同一用户重复购买'], evidence: { demand: 2, circle_stock: 0, distribution_stock: 4, cost_price: 120, discount_price: 120 } }] },
        { order_no: '111-0000000-0000001', seller: 'DEMOA_US_US', buyer_id: 'demo_buyer_d', status: 'pass', reasons: [], lines: [{ platform_sku: 'W5515P080025-th-zy', warehouse_sku: 'W5515P080024', qty: 1, reasons: [], evidence: { demand: 1, circle_stock: 8, distribution_stock: 97, cost_price: 172, discount_price: 172 } }] },
        { order_no: '115-0000000-0000030', seller: 'DEMOD_US', buyer_id: 'demo_buyer_e', status: 'pass', reasons: [], lines: [{ platform_sku: 'W9000P001-ZE-HR', warehouse_sku: 'WH-LAMP-03', qty: 1, reasons: [], evidence: { demand: 1, circle_stock: 0, distribution_stock: 8, cost_price: 20, discount_price: 22 } }] },
      ],
    };
    renderResults();
    toast('已加载演示数据，点击订单记录查看原因与证据');
    $('#results').scrollIntoView({ behavior: 'smooth', block: 'start' });
  };
  const copyText = async (text, successMessage) => {
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(text);
      else {
        const area = document.createElement('textarea');
        area.value = text;
        document.body.appendChild(area);
        area.select();
        document.execCommand('copy');
        area.remove();
      }
      toast(successMessage);
      return true;
    } catch {
      toast('\u590d\u5236\u5931\u8d25\uff0c\u8bf7\u624b\u52a8\u9009\u4e2d\u8ba2\u5355\u53f7');
      return false;
    }
  };
  const copyOrders = async () => {
    if (!state.result) return;
    const numbers = (state.result.orders || []).filter((order) => order.status === 'manual').map((order) => order.order_no);
    let text = numbers.join(' ');
    if (state.result.run_id) {
      try {
        const response = await fetch('/api/copy-orders', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ order_numbers: numbers }) });
        text = (await response.json()).text || text;
      } catch {
        // Keep the client-side order list as a fallback if the helper endpoint is unavailable.
      }
    }
    await copyText(text, '\u5df2\u590d\u5236\u4eba\u5de5\u8ba2\u5355\u53f7');
  };
  const setManualExpanded = (expanded) => {
    $('#manual-toggle').setAttribute('aria-expanded', String(expanded));
    $('#manual-content').hidden = !expanded;
    $('.manual-toggle-label').textContent = expanded ? '\u6536\u8d77\u5217\u8868' : '\u5c55\u5f00\u5217\u8868';
  };
  const reset = () => {
    state.erpFile = null;
    state.inventoryFiles = [];
    state.result = null;
    $('#erp-file').value = '';
    $('#inventory-file').value = '';
    renderFiles();
    ['#kpi-total', '#kpi-manual', '#kpi-pass', '#kpi-sku', '#manual-section-count', '#pass-section-count'].forEach((id) => $(id).textContent = '0');
    $('#rail-manual-count').textContent = '等待审单';
    $('#rail-pass-count').textContent = '等待审单';
    $('#manual-list').innerHTML = '';
    $('#pass-orders').innerHTML = '';
    $('#manual-empty').hidden = false;
    setManualExpanded(true);
    $('#copy-button').disabled = true;
    $('#export-button').classList.add('is-disabled');
    $('#export-button').href = '#';
    $('#search-input').value = '';
    $('#store-filter').innerHTML = '<option value="">全部店铺</option>';
    $('#reason-filter').innerHTML = '<option value="">全部原因</option>';
    $('#pass-orders').hidden = true;
    $('#pass-toggle').setAttribute('aria-expanded', 'false');
    toast('已清空，可开始新一轮审单');
  };
  const dropzone = (label, input, handler) => {
    ['dragenter', 'dragover'].forEach((name) => label.addEventListener(name, (event) => { event.preventDefault(); label.classList.add('is-dragging'); }));
    ['dragleave', 'drop'].forEach((name) => label.addEventListener(name, (event) => { event.preventDefault(); label.classList.remove('is-dragging'); }));
    label.addEventListener('drop', (event) => { const files = [...(event.dataTransfer?.files || [])]; if (files.length) handler(files); });
    input.addEventListener('change', () => handler([...input.files]));
  };
  dropzone($('.erp-zone'), $('#erp-file'), (files) => {
    const file = files[0];
    if (!file?.name.toLowerCase().endsWith('.xlsx')) { toast('只支持 .xlsx 文件'); return; }
    state.erpFile = file;
    renderFiles();
  });
  dropzone($('.inventory-zone'), $('#inventory-file'), (files) => {
    const valid = files.filter((file) => file.name.toLowerCase().endsWith('.xlsx'));
    if (valid.length !== files.length) toast('已跳过非 .xlsx 文件');
    state.inventoryFiles = valid.map((file) => ({ file, name: file.name, seller: detectStore(file.name) }));
    renderFiles();
  });
  $('#audit-button').addEventListener('click', auditFiles);
  $('#demo-button').addEventListener('click', demo);
  $('#copy-button').addEventListener('click', copyOrders);
  $('#reset-button').addEventListener('click', reset);
  $('#manual-toggle').addEventListener('click', () => {
    setManualExpanded($('#manual-toggle').getAttribute('aria-expanded') !== 'true');
  });
  $('#pass-toggle').addEventListener('click', () => {
    const open = $('#pass-toggle').getAttribute('aria-expanded') === 'true';
    $('#pass-toggle').setAttribute('aria-expanded', String(!open));
    $('#pass-orders').hidden = open;
  });
  ['#search-input', '#store-filter', '#reason-filter', '#presale-filter'].forEach((id) => $(id).addEventListener('input', renderResults));
  renderFiles();
})();

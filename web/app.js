'use strict';
const $ = id => document.getElementById(id);
const names = ['interface', 'interface_cidr', 'destination_cidr', 'next_hop'];
const stageNames = ['Template syntax', 'Parameter rendering', 'Command structure', 'Intent agreement', 'Local route model'];
let statusData, report, selectedAttempt = 0, codeTab = 'template', benchmarkReport, noticeTimer;
let liveBenchmarkReport;
const escapeHtml = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));

function notify(message, error = false) {
  clearTimeout(noticeTimer);
  $('notice').textContent = message;
  $('notice').className = 'notice' + (error ? ' error' : '');
  $('notice').hidden = false;
  if (!error) noticeTimer = setTimeout(() => $('notice').hidden = true, 7000);
}
async function api(path, payload) {
  const response = await fetch(path, payload === undefined ? {} : {
    method:'POST', headers:{'Content-Type':'application/json', 'X-VerifyNet':'1'}, body:JSON.stringify(payload)
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'The request could not be completed.');
  return result;
}
function intent() {
  if (['cisco_ios','juniper_junos'].includes($('task-profile').value)) return {vendor:$('task-profile').value, interface:$('vendor-interface').value.trim(), interface_cidr:$('interface_cidr').value.trim(), destination_cidr:$('destination_cidr').value.trim(), next_hop:$('next_hop').value.trim()};
  if ($('task-profile').value === 'ospf') return {router_id:$('router-id').value.trim(), area:$('ospf-area').value.trim(), network_cidr:$('ospf-network').value.trim()};
  if ($('task-profile').value === 'vlan_static') return {interface:$('interface').value.trim(), vlan_id:$('vlan-id').value.trim(), interface_cidr:$('interface_cidr').value.trim(), destination_cidr:$('destination_cidr').value.trim(), next_hop:$('next_hop').value.trim()};
  if ($('task-profile').value === 'multi_route') return {interfaces:[{name:$('interface').value.trim(), cidr:$('interface_cidr').value.trim()},{name:$('interface-2').value.trim(), cidr:$('interface-cidr-2').value.trim()}], routes:[{destination:$('destination_cidr').value.trim(), next_hop:$('next_hop').value.trim()},{destination:$('destination-cidr-2').value.trim(), next_hop:$('next-hop-2').value.trim()}]};
  return Object.fromEntries(names.map(n => [n, $(n).value.trim()]));
}
function taskProfileChanged() {
  const advanced = $('task-profile').value === 'multi_route';
  const ipv6 = $('task-profile').value === 'ipv6_static';
  const vlan = $('task-profile').value === 'vlan_static';
  const ospf = $('task-profile').value === 'ospf';
  const vendor = ['cisco_ios','juniper_junos'].includes($('task-profile').value);
  $('multi-intent-panel').hidden = !advanced;
  $('ospf-panel').hidden = !ospf;
  $('vlan-field').hidden = !vlan;
  $('vendor-panel').hidden = !vendor;
  $('task-profile-help').textContent = advanced ? 'The checker will require two reusable interface blocks and two static route commands, then render alternate multi-interface cases.' : ipv6 ? 'The checker will require IPv6 address and route commands, then render alternate IPv6 parameter sets.' : vlan ? 'The checker will require an 802.1Q VLAN ID, interface address, and static route.' : ospf ? 'The checker will require a router ID, area, and advertised network; neighbor formation needs the OSPF lab.' : vendor ? 'The checker will require vendor-specific interface and static-route syntax.' : 'The checker will require one reusable IPv4 interface block and one static route.';
  if ($('task-profile').value === 'juniper_junos') $('vendor-interface').value = 'ge-0/0/1';
  if ($('task-profile').value === 'cisco_ios') $('vendor-interface').value = 'GigabitEthernet0/1';
  if (ipv6) {
    $('interface_cidr').value = '2001:db8:10::1/64'; $('destination_cidr').value = '2001:db8:20::/64'; $('next_hop').value = '2001:db8:10::2';
    $('requirement').value = 'Configure an IPv6 interface and static IPv6 route to the remote network through the specified next hop.';
  } else if (vlan) {
    $('vlan-id').value = '100'; $('interface_cidr').value = '10.100.0.1/30'; $('destination_cidr').value = '192.168.100.0/24'; $('next_hop').value = '10.100.0.2';
    $('requirement').value = 'Configure an 802.1Q VLAN interface and a static IPv4 route to the remote network through the specified next hop.';
  } else if (ospf) {
    $('router-id').value = '1.1.1.1'; $('ospf-area').value = '0.0.0.0'; $('ospf-network').value = '10.0.0.0/30';
    $('requirement').value = 'Configure OSPF with the specified router ID, area, and advertised network.';
  } else if ($('interface_cidr').value.includes(':')) {
    $('interface_cidr').value = '10.10.0.1/30'; $('destination_cidr').value = '192.168.20.0/24'; $('next_hop').value = '10.10.0.2';
    $('requirement').value = advanced ? 'Configure two interfaces and static IPv4 routes to two remote networks through their specified next hops.' : 'Configure an interface and a static IPv4 route to the remote network through the specified next hop.';
  } else {
    $('requirement').value = advanced ? 'Configure two interfaces and static IPv4 routes to two remote networks through their specified next hops.' : 'Configure an interface and a static IPv4 route to the remote network through the specified next hop.';
  }
}
function download(name, value, mime = 'application/json') {
  const url = URL.createObjectURL(new Blob([typeof value === 'string' ? value : JSON.stringify(value, null, 2)], {type:mime}));
  const link = document.createElement('a'); link.href = url; link.download = name; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
function busy(value) {
  for (const el of document.querySelectorAll('#run-form button, #run-form select, #run-form input, #run-form textarea')) el.disabled = value;
  $('run-form').setAttribute('aria-busy', String(value));
  if (!value) $('max_repairs').disabled = $('strategy').value !== 'rag_repair';
  $('run-button').firstElementChild.textContent = value ? 'Running checks…' : $('mode').value === 'demo' ? 'Run walkthrough' : 'Generate & check';
}
function modeChanged() {
  const live = $('mode').value === 'live';
  $('mode-help').textContent = live ? 'Calls your configured AI model. The requirement, parameters, references, and error context are sent to the provider.' : 'A known broken example demonstrates the checker and repair flow. No AI model is called.';
  $('button-footnote').textContent = live ? 'Live API usage may incur charges · up to 4 calls per run' : 'Local demo · no API usage';
  $('run-button').firstElementChild.textContent = live ? 'Generate & check' : 'Run walkthrough';
}
function showSources(docs) {
  $('sources').innerHTML = docs.length ? docs.map(d => sourceCard(d)).join('') : '<p class="sources-intro">No reference documents were supplied for this generation-only run.</p>';
}
function sourceCard(d, showScore = false) {
  const location = d.start_line ? ` · lines ${d.start_line}–${d.end_line}` : '';
  return `<details class="source"><summary><span>${escapeHtml(d.title + location)}</span><small>${showScore ? `SCORE ${Number(d.score).toFixed(2)}` : '↗'}</small></summary><p class="source-excerpt">${escapeHtml(d.text)}</p>${d.url ? `<a href="${escapeHtml(d.url)}" target="_blank" rel="noopener noreferrer">${d.kind === 'Project specification' ? 'Project specification' : d.document_id ? 'Source link' : 'Official documentation'} ↗</a>` : '<span class="source-type">No external source link</span>'}<p class="source-type">${escapeHtml(d.kind)}${d.document_id ? ' · imported ' + escapeHtml(d.imported_at.slice(0,10)) : ' · reviewed ' + escapeHtml(d.reviewed)}</p><p class="source-type">${escapeHtml(d.id)}</p></details>`;
}
function showCode() {
  if (!report) return;
  const a = report.attempts[selectedAttempt];
  const values = {template:a.template, rendered:a.validation.rendered[0] || 'No configuration could be rendered.', diff:a.diff || 'No earlier attempt to compare.'};
  $('code-output').textContent = values[codeTab];
  $('code-filename').textContent = {template:'template.j2', rendered:'candidate.conf · first parameter set', diff:'repair.diff'}[codeTab];
  document.querySelectorAll('[data-code]').forEach(button => {
    button.classList.toggle('selected', button.dataset.code === codeTab);
    button.setAttribute('aria-selected', String(button.dataset.code === codeTab));
  });
}
function showAttempt(index) {
  selectedAttempt = index;
  const a = report.attempts[index];
  $('result-badge').className = 'pill' + (a.validation.passed ? '' : ' fail');
  $('result-badge').textContent = `ATTEMPT ${index + 1}: ${a.validation.passed ? 'LOCAL PASS' : 'FAILED'}`;
  document.querySelectorAll('.attempt-button').forEach((button, i) => button.classList.toggle('active', i === index));
  $('explanation-text').textContent = a.explanation;
  const cited = (a.source_ids || []).map(id => report.documents.find(d => d.id === id)).filter(Boolean).map(d => d.title + (d.start_line ? ` (lines ${d.start_line}–${d.end_line})` : ''));
  $('citation-text').textContent = cited.length ? 'Model-referenced sources: ' + cited.join(' · ') : a.provider === 'scripted_demo' ? 'Scripted content. Reference material is displayed separately.' : 'No source citations returned.';
  $('checks').innerHTML = stageNames.map(name => {
    const stage = a.validation.stages.find(s => s.name === name);
    const cls = !stage ? 'skipped' : stage.passed ? '' : 'failed';
    return `<div class="check-row ${cls}"><span class="check-symbol">${!stage ? '–' : stage.passed ? '✓' : '×'}</span><div><div class="check-name">${name}</div><div class="check-detail">${escapeHtml(stage?.detail || 'Not run because an earlier stage failed.')}</div>${(stage?.errors || []).map(e => `<div class="check-error">${escapeHtml(e)}</div>`).join('')}</div></div>`;
  }).join('');
  showCode();
}
function showReport(data) {
  report = data;
  $('empty-state').hidden = true;
  $('result-content').hidden = false;
  $('result-badge').className = 'pill' + (data.final_pass ? '' : ' fail');
  $('result-badge').textContent = data.final_pass ? 'LOCAL CHECKS PASSED' : 'CHECKS FAILED';
  const modeLabel = data.mode === 'demo' ? 'SCRIPTED DEMO' : data.mode === 'validation' ? 'CHECK ONLY' : 'LIVE AI';
  const deviceLabel = data.device_tested ? 'Device tested' : 'Local checks only';
  const deviceDetail = data.device_tested ? 'Virtual-router evidence included' : 'No packet test was run';
  $('run-summary').innerHTML = `<div class="summary-heading"><strong>${modeLabel}</strong><span>${escapeHtml(data.notice)}</span></div><div class="summary-grid"><div class="summary-metric ${data.final_pass ? 'good' : 'bad'}"><small>VALIDATION</small><b>${data.final_pass ? 'PASSED' : 'FAILED'}</b><span>${data.final_pass ? 'All local stages passed' : 'Review the failed checks'}</span></div><div class="summary-metric"><small>ATTEMPTS</small><b>${data.attempts.length}</b><span>${data.repairs} repair${data.repairs === 1 ? '' : 's'} used</span></div><div class="summary-metric"><small>REFERENCES</small><b>${data.documents.length}</b><span>${data.documents.length ? 'Sources supplied' : 'Generation only'}</span></div><div class="summary-metric ${data.device_tested ? 'good' : ''}"><small>VERIFICATION</small><b>${deviceLabel}</b><span>${deviceDetail}</span></div></div>`;
  $('attempts').innerHTML = data.attempts.map((a, i) => `<button class="attempt-button" type="button" data-attempt="${i}">Attempt ${i + 1} <span class="${a.validation.passed ? 'good' : 'bad'}">${a.validation.passed ? '✓' : '×'}</span></button>`).join('');
  $('attempts').querySelectorAll('button').forEach(b => b.addEventListener('click', () => showAttempt(Number(b.dataset.attempt))));
  showAttempt(data.attempts.length - 1);
  showSources(data.documents);
  $('export-config').disabled = !data.attempts.at(-1).validation.rendered.length;
  $('feedback-panel').hidden = !data.history_id;
  $('feedback-status').textContent = '';
  $('feedback-note').value = '';
  $('run-result-router').hidden = !(data.final_pass && data.history_id && ['single_route','multi_route','ipv6_static','vlan_static','ospf'].includes(data.task_profile));
  $('run-result-router').disabled = false;
  if (data.provider_error) notify('Repair stopped: ' + data.provider_error, true);
}
function navigate(viewName) {
  document.querySelectorAll('.view').forEach(view => view.hidden = view.id !== 'view-' + viewName);
  document.querySelectorAll('[data-view]').forEach(b => b.classList.toggle('active', b.dataset.view === viewName));
  $('breadcrumb').textContent = {lab:'Template lab', benchmark:'Evaluation', method:'How it works', library:'Reference library', setup:'AI setup', router:'Router lab', topology:'Network topology', history:'Run history'}[viewName];
  if (viewName === 'library') refreshLibrary().catch(error => notify(error.message, true));
  if (viewName === 'history') refreshHistory().catch(error => notify(error.message, true));
  window.scrollTo({top:0, behavior:'smooth'});
}
document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => navigate(button.dataset.view)));
$('topology-refresh').addEventListener('click', async () => {
  const button = $('topology-refresh');
  const checked = $('topology-last-checked');
  button.disabled = true;
  button.textContent = 'Checking…';
  try {
    const [status, router] = await Promise.all([api('/api/status'), fetch('/api/router/status').then(response => response.json())]);
    const healthy = Boolean(status && status.connection);
    $('topology-health-score').textContent = healthy ? '87%' : '0%';
    checked.textContent = `Last checked ${new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})} · ${healthy ? 'workspace connected' : 'workspace unavailable'}`;
    const labStatus = $('topology-lab-status');
    labStatus.innerHTML = `<span class="legend-dot ${router.ready ? 'online' : 'warning'}"></span> Router Lab: ${escapeHtml(router.ready ? 'ready for virtual-router tests' : (router.message || 'unavailable'))}`;
    notify(healthy ? 'Topology status refreshed.' : 'The workspace is unavailable.', !healthy);
  } catch (error) {
    $('topology-health-score').textContent = '0%';
    checked.textContent = `Last checked ${new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})} · unavailable`;
    notify('Topology status could not be refreshed.', true);
  } finally {
    button.disabled = false;
    button.textContent = 'Refresh status';
  }
});
$('topology-open-router').addEventListener('click', () => navigate('router'));
$('mode').addEventListener('change', modeChanged);
$('strategy').addEventListener('change', () => $('max_repairs').disabled = $('strategy').value !== 'rag_repair');
document.querySelectorAll('[data-code]').forEach(b => b.addEventListener('click', () => {codeTab = b.dataset.code; showCode();}));
$('load-broken').addEventListener('click', () => {$('custom-template').value = $('task-profile').value === 'multi_route' ? statusData.multi_template : $('task-profile').value === 'ipv6_static' ? statusData.ipv6_broken_template : $('task-profile').value === 'vlan_static' ? statusData.vlan_broken_template : $('task-profile').value === 'ospf' ? statusData.ospf_broken_template : statusData.broken_template;});
$('task-profile').addEventListener('change', taskProfileChanged);
$('run-form').addEventListener('submit', async event => {
  event.preventDefault();
  const payload = {task_profile:$('task-profile').value, intent:intent(), requirement:$('requirement').value, mode:$('mode').value, strategy:$('strategy').value, max_repairs:Number($('max_repairs').value)};
  if ($('paste-details').open && $('custom-template').value.trim()) payload.template = $('custom-template').value;
  busy(true); $('notice').hidden = true;
  if (payload.mode === 'live') notify('Waiting for the AI provider. Each attempt can take up to a minute.');
  try { showReport(await api('/api/run', payload)); }
  catch (error) { notify(error.message, true); }
  finally { busy(false); }
});
$('validate-only').addEventListener('click', async () => {
  const template = $('custom-template').value;
  busy(true);
  try {
    const validation = await api('/api/validate', {task_profile:$('task-profile').value, template, intent:intent()});
    showReport({mode:'validation', intent:intent(), documents:[], repairs:0, final_pass:validation.passed, first_pass:validation.passed,
      device_tested:false, notice:'Local checks only. No AI call and no router execution.',
      attempts:[{template, validation, explanation:'User-supplied template evaluated against the explicit intent and two additional parameter sets.', provider:'user', source_ids:[], diff:''}]});
  } catch(error) { notify(error.message, true); }
  finally { busy(false); }
});
$('copy-code').addEventListener('click', async () => {
  try { await navigator.clipboard.writeText($('code-output').textContent); notify('Copied to clipboard.'); }
  catch { notify('Clipboard access is unavailable. Select and copy the displayed text.', true); }
});
$('export-report').addEventListener('click', () => download('verifynet-evidence.json', report));
$('export-pdf-report').addEventListener('click', async () => { if (!report) return; try { const response = await fetch('/api/report/pdf', {method:'POST', headers:{'Content-Type':'application/json','X-VerifyNet':'1'}, body:JSON.stringify({report})}); if (!response.ok) throw new Error('PDF export failed.'); const blob = await response.blob(); const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = 'verifynet-evidence.pdf'; link.click(); URL.revokeObjectURL(url); } catch (error) { notify(error.message, true); } });
$('export-thesis-report').addEventListener('click', () => {
  if (!report) return;
  const latest = report.attempts.at(-1);
  const checks = (latest.validation.stages || []).map(stage => `- ${stage.passed ? 'PASS' : 'FAIL'} — ${stage.name}: ${stage.detail}${stage.errors?.length ? `\n  - ${stage.errors.join('\n  - ')}` : ''}`).join('\n');
  const sources = (report.documents || []).map(doc => `- ${doc.title}${doc.url ? ` (${doc.url})` : ''}${doc.start_line ? `, lines ${doc.start_line}–${doc.end_line}` : ''}`).join('\n') || '- None supplied';
  const attempts = report.attempts.map((attempt, index) => `### Attempt ${index + 1}\nProvider: ${attempt.provider || 'unknown'}\nPassed: ${attempt.validation.passed}\n\n${attempt.explanation}\n\n\`\`\`text\n${attempt.template}\n\`\`\``).join('\n\n');
  const routerEvidence = routerReport ? `\n## Virtual-router evidence\n- Status: ${routerReport.status}\n- Passed: ${routerReport.passed}\n- Verification level: ${routerReport.verification_level}\n- FRRouting version: ${routerReport.router_version || 'n/a'}\n- Target IP: ${routerReport.target_ip || 'n/a'}\n\n${(routerReport.checks || []).map(check => `- ${check.passed ? 'PASS' : 'FAIL'} — ${check.name}: ${check.detail}`).join('\n')}` : '\n## Virtual-router evidence\nNo virtual-router test was run for this result.';
  const markdown = `# VerifyNet thesis evidence report\n\nGenerated: ${new Date().toISOString()}\n\n## Research question\nCan independent verification improve AI-generated network configuration templates?\n\n## Experiment\n- Mode: ${report.mode}\n- Task profile: ${report.task_profile || 'single_route'}\n- Strategy: ${report.strategy || 'validation'}\n- Requirement: ${report.requirement || 'User-supplied template'}\n- First-pass result: ${report.first_pass}\n- Final result: ${report.final_pass}\n- Repairs: ${report.repairs}\n- Device tested: ${report.device_tested}\n- Duration: ${report.duration_seconds ?? 'n/a'} seconds\n\n## Intent\n\`\`\`json\n${JSON.stringify(report.intent, null, 2)}\n\`\`\`\n\n## Retrieved references\n${sources}\n\n## Attempts\n${attempts}\n\n## Independent validation\n${checks}\n${routerEvidence}\n\n## Limitations\nThis report records VerifyNet’s local evidence. A local pass is not a guarantee of production-device acceptance unless a separate virtual-router or hardware test is recorded.\n`;
  download('verifynet-thesis-evidence.md', markdown, 'text/markdown');
});
$('export-config').addEventListener('click', () => {
  const latest = report.attempts.at(-1);
  const label = latest.validation.passed ? 'locally-checked-candidate.conf' : 'failed-candidate.conf';
  download(label, '! VerifyNet candidate: local checks only; not device-tested.\n' + latest.validation.rendered[0], 'text/plain');
});
document.querySelectorAll('[data-feedback]').forEach(button => button.addEventListener('click', async () => {
  if (!report?.history_id) return;
  document.querySelectorAll('[data-feedback]').forEach(item => item.disabled = true);
  try {
    await api('/api/feedback', {run_id:report.history_id, verdict:button.dataset.feedback, note:$('feedback-note').value});
    $('feedback-status').textContent = 'Review saved locally. Thank you.';
    document.querySelectorAll('[data-feedback]').forEach(item => item.classList.toggle('selected', item === button));
  } catch (error) { $('feedback-status').textContent = error.message; }
  finally { document.querySelectorAll('[data-feedback]').forEach(item => item.disabled = false); }
}));
$('run-benchmark').addEventListener('click', async () => {
  $('run-benchmark').disabled = true;
  try {
    benchmarkReport = await api('/api/benchmark', {});
    $('benchmark-summary').innerHTML = `<p class="benchmark-score">${benchmarkReport.correct_verdicts}<small> / ${benchmarkReport.cases} expected verdicts</small></p><p class="field-help">Offline checker regression · no model calls</p>`;
    $('benchmark-rows').innerHTML = benchmarkReport.results.map(r => `<tr><td>${escapeHtml(r.id)}</td><td>${escapeHtml(r.fault)}</td><td>${r.expected_pass ? 'Pass' : 'Fail'}</td><td>${r.actual_pass ? 'Pass' : 'Fail'}</td><td>${r.correct_verdict ? '✓ Matched' : '× Mismatch'}</td></tr>`).join('');
    $('benchmark-results').hidden = false;
  } catch(error) { notify(error.message, true); }
  finally { $('run-benchmark').disabled = false; }
});
$('export-benchmark').addEventListener('click', () => download('verifynet-checker-regression.json', benchmarkReport));
$('run-live-benchmark').addEventListener('click', async () => {
  $('run-live-benchmark').disabled = true; $('live-benchmark-status').textContent = 'Running three strategies. This may take several minutes and use API credits.';
  try {
    liveBenchmarkReport = await api('/api/live-benchmark', {limit:Number($('live-benchmark-limit').value), split:$('live-benchmark-split').value});
    $('live-benchmark-results').hidden = false;
    const labels = {llm_only:'Generation only', rag:'Retrieval + generation', rag_repair:'Retrieval + repair'};
    $('live-benchmark-summary').textContent = liveBenchmarkReport.notice;
    $('live-metrics').innerHTML = `<table><thead><tr><th>STRATEGY</th><th>FIRST PASS</th><th>FINAL PASS</th><th>REPAIRS</th><th>AVG TIME</th><th>TOKENS</th></tr></thead><tbody>${Object.entries(liveBenchmarkReport.metrics).map(([key, metric]) => `<tr><td><strong>${labels[key]}</strong></td><td>${Math.round(metric.first_pass_rate * 100)}%</td><td><span class="history-result ${metric.final_pass_rate === 1 ? 'pass' : 'fail'}">${Math.round(metric.final_pass_rate * 100)}%</span></td><td>${metric.repairs}</td><td>${Number(metric.average_duration_seconds).toFixed(2)}s</td><td>${metric.total_tokens || '—'}</td></tr>`).join('')}</tbody></table>`;
    download('verifynet-live-ablation.json', liveBenchmarkReport);
  } catch (error) { $('live-benchmark-status').textContent = error.message; }
  finally { $('run-live-benchmark').disabled = !statusData?.connection?.configured; }
});
let routerReport;
function renderRouterReport() {
  $('router-results').hidden = false;
  $('router-summary').innerHTML = `<p class="run-summary"><strong>${routerReport.passed ? 'VIRTUAL ROUTER PASS' : 'VIRTUAL ROUTER FAILED'}</strong> · ${escapeHtml(routerReport.status)} · ${escapeHtml(routerReport.scope)}</p>`;
  $('router-checks').innerHTML = (routerReport.checks || []).map(c => `<div class="check-row ${c.passed ? '' : 'failed'}"><span class="check-symbol">${c.passed ? '✓' : '×'}</span><div><div class="check-name">${escapeHtml(c.name)}</div><div class="check-detail">${escapeHtml(c.detail)}</div></div></div>`).join('') || `<p class="field-help">${escapeHtml(routerReport.error || 'No checks were run.')}</p>`;
  $('router-run-status').textContent = routerReport.error || (routerReport.passed ? 'Evidence complete. Containers were cleaned up.' : 'The run stopped safely; inspect the evidence above.');
}
async function executeRouterTest(fromResult = false) {
  if (!report?.final_pass && fromResult) throw new Error('Run local validation successfully before starting the router test.');
  $('router-run').disabled = true; $('run-result-router').disabled = true; $('router-run-status').textContent = 'Starting isolated containers and running checks…';
  try {
    const latest = report?.attempts?.at(-1);
    const template = latest?.template || statusData.reference_template;
    routerReport = await api('/api/router/run', {task_profile:$('task-profile').value, template, intent:intent(), source_run_id:report?.history_id || null});
    renderRouterReport();
    if (fromResult) navigate('router');
  } finally { $('router-run').disabled = false; $('run-result-router').disabled = false; refreshRouterStatus(); }
}
async function refreshRouterStatus() {
  try {
    const response = await fetch('/api/router/status');
    const data = await response.json();
    $('router-status-badge').textContent = data.ready ? 'READY' : 'UNAVAILABLE';
    $('router-status-badge').className = 'pill' + (data.ready ? '' : ' neutral');
    $('router-status-text').textContent = data.message || 'Docker readiness is unavailable.';
    $('router-run').disabled = !data.ready;
  } catch (error) { $('router-status-text').textContent = 'The router-lab endpoint is unavailable. Restart VerifyNet.'; $('router-run').disabled = true; }
}
$('router-refresh').addEventListener('click', refreshRouterStatus);
$('router-run').addEventListener('click', async () => {
  try { await executeRouterTest(false); } catch (error) { $('router-run-status').textContent = error.message; $('router-run').disabled = false; }
});
$('run-result-router').addEventListener('click', async () => {
  try { await executeRouterTest(true); } catch (error) { notify(error.message, true); $('run-result-router').disabled = false; }
});
$('export-router').addEventListener('click', () => { if (routerReport) download('verifynet-router-evidence.json', routerReport); });
function formatDate(value) { try { return new Intl.DateTimeFormat(undefined, {dateStyle:'medium', timeStyle:'short'}).format(new Date(value)); } catch { return 'Unknown date'; } }
function refreshHistory() {
  return Promise.all([fetch('/api/history').then(response => response.json()), fetch('/api/feedback').then(response => response.json()), fetch('/api/versions').then(response => response.json())]).then(([{runs}, feedback, {versions}]) => {
    const generation = runs.filter(r => r.kind === 'generation');
    const passed = generation.filter(r => r.final_pass).length;
    const repairs = generation.reduce((sum, r) => sum + (r.repairs || 0), 0);
    $('history-metrics').innerHTML = `<div class="history-metric"><small>TOTAL RUNS</small><b>${runs.length}</b><span>Local experiment records</span></div><div class="history-metric good"><small>FINAL PASS RATE</small><b>${generation.length ? Math.round(passed / generation.length * 100) : 0}%</b><span>${passed} of ${generation.length} generation runs</span></div><div class="history-metric"><small>REPAIRS</small><b>${repairs}</b><span>Across generation runs</span></div><div class="history-metric"><small>DEVICE TESTS</small><b>${runs.filter(r => r.device_tested).length}</b><span>Virtual-router evidence</span></div>`;
    const byStrategy = ['llm_only','rag','rag_repair'].map(strategy => { const rows = generation.filter(run => run.strategy === strategy); return {strategy, rate:rows.length ? Math.round(rows.filter(run => run.final_pass).length / rows.length * 100) : 0, count:rows.length}; });
    $('strategy-chart').innerHTML = byStrategy.some(row => row.count) ? byStrategy.map(row => `<div class="bar-row"><span>${row.strategy === 'llm_only' ? 'Generation only' : row.strategy === 'rag' ? 'Retrieval + generation' : 'Retrieval + repair'}</span><div class="bar-track"><i style="width:${row.rate}%"></i></div><b>${row.rate}%</b><small>${row.count} run${row.count === 1 ? '' : 's'}</small></div>`).join('') : '<p class="history-empty">Run experiments to build this chart.</p>';
    const feedbackLabels = {correct:'Correct', partially_correct:'Partially correct', incorrect:'Incorrect', unsafe:'Unsafe'};
    const feedbackRows = Object.entries(feedback.summary || {}).map(([key, count]) => `<div class="bar-row feedback-row"><span>${feedbackLabels[key] || key}</span><div class="bar-track"><i class="feedback-${key}" style="width:${runs.length ? Math.min(100, count / Math.max(1, runs.length) * 100) : 0}%"></i></div><b>${count}</b></div>`).join('');
    $('evidence-chart').innerHTML = feedbackRows || '<p class="history-empty">Human review labels will appear here.</p>';
    const measured = generation.length ? {
      latency: generation.reduce((sum, run) => sum + Number(run.duration_seconds || 0), 0) / generation.length,
      repairs: generation.reduce((sum, run) => sum + Number(run.repairs || 0), 0) / generation.length,
      first: generation.filter(run => run.first_pass).length / generation.length * 100,
      final: generation.filter(run => run.final_pass).length / generation.length * 100,
      references: generation.reduce((sum, run) => sum + Number(run.reference_count || 0), 0) / generation.length
    } : null;
    $('research-chart').innerHTML = measured ? [['Latency', measured.latency.toFixed(2) + 's'], ['Repairs', measured.repairs.toFixed(2) + ' avg'], ['First-pass accuracy', Math.round(measured.first) + '%'], ['Final accuracy', Math.round(measured.final) + '%'], ['References', measured.references.toFixed(2) + ' avg']].map(([label,value]) => `<div class="bar-row"><span>${label}</span><b>${value}</b></div>`).join('') : '<p class="history-empty">Run experiments to measure latency, repairs, accuracy, and references.</p>';
    $('case-detail-select').innerHTML = '<option value="">Choose a run</option>' + runs.map(run => `<option value="${escapeHtml(run.id)}">${escapeHtml(formatDate(run.created_at))} · ${escapeHtml(run.task_profile || run.kind || 'run')} · ${escapeHtml(run.strategy || 'router')}</option>`).join('');
    $('case-detail-select').onchange = event => { const selected = runs.find(run => run.id === event.target.value); $('case-detail').textContent = selected ? JSON.stringify(selected, null, 2) : 'Select a run to inspect its intent, strategy, timing, references, and outcome.'; };
    $('version-list').innerHTML = versions.length ? versions.map(version => `<div class="version-row"><div><strong>${escapeHtml(version.task_profile)}</strong><small>${escapeHtml(formatDate(version.created_at))} · ${escapeHtml(version.config_sha256.slice(0,12))}…</small></div><button class="text-button" type="button" data-version="${escapeHtml(version.version_id)}">Restore copy</button></div>`).join('') : '<p class="history-empty">No configuration versions recorded yet.</p>';
    $('version-list').querySelectorAll('[data-version]').forEach(button => button.addEventListener('click', async () => {
      button.disabled = true;
      try { const version = await api('/api/versions/restore', {version_id:button.dataset.version}); download(`${version.task_profile}-${version.version_id}.j2`, version.template, 'text/plain'); notify('A reviewed copy of the configuration version was downloaded.'); }
      catch (error) { notify(error.message, true); }
      finally { button.disabled = false; }
    }));
    const profileFilter = $('history-profile-filter')?.value || ''; const strategyFilter = $('history-strategy-filter')?.value || '';
    const visibleRuns = runs.filter(run => (!profileFilter || (run.intent && run.intent.vendor === profileFilter) || run.task_profile === profileFilter || (profileFilter === 'single_route' && !run.task_profile)) && (!strategyFilter || run.strategy === strategyFilter));
    $('history-rows').innerHTML = visibleRuns.length ? visibleRuns.map(run => {
      const isRouter = run.kind === 'router'; const pass = isRouter ? run.passed : run.final_pass;
      return `<tr><td>${escapeHtml(formatDate(run.created_at))}</td><td>${isRouter ? 'Router lab' : escapeHtml(run.mode || 'Generation')}</td><td>${isRouter ? 'Device test' : escapeHtml(run.strategy || '—')}</td><td><span class="history-result ${pass ? 'pass' : 'fail'}">${pass ? 'PASS' : 'FAIL'}</span></td><td>${isRouter ? '—' : run.repairs}</td><td>${isRouter ? '—' : run.reference_count}</td><td>${Number(run.duration_seconds || 0).toFixed(2)}s</td></tr>`;
    }).join('') : '<tr><td colspan="7" class="history-empty">No matching runs.</td></tr>';
  });
}
['history-profile-filter','history-strategy-filter'].forEach(id => $(id)?.addEventListener('change', refreshHistory));
function updateConnection(connection) {
  const active = connection.configured;
  $('live-option').disabled = !active;
  $('live-option').textContent = active ? `Live AI · ${connection.model}` : 'Live AI · connect a model in AI setup';
  $('connection-badge').textContent = active ? 'CONFIGURED' : 'NOT CONFIGURED';
  $('connection-badge').className = 'pill' + (active ? '' : ' neutral');
  $('disconnect-button').hidden = !active;
  $('run-live-benchmark').disabled = !active;
  $('run-live-benchmark').firstElementChild.textContent = active ? 'Run live comparison' : 'Connect a model first';
  if (active) $('model-id').value = connection.model;
  $('connection-message').textContent = active ? (connection.access_verified ? `Model access verified for ${connection.model}. Generation compatibility still needs a live run.` : `Configured through the server environment: ${connection.model}. Model access has not been checked here.`) : 'Demo mode is available. Connect a model when you are ready for live generation.';
  if (!active) { $('mode').value = 'demo'; modeChanged(); }
}
$('open-ai-setup').addEventListener('click', () => navigate('setup'));
$('setup-to-lab').addEventListener('click', () => navigate('lab'));
$('connection-form').addEventListener('submit', async event => {
  event.preventDefault();
  const credentials = {api_key:$('api-key').value, model:$('model-id').value};
  $('api-key').value = '';
  $('connect-button').disabled = true;
  $('connection-message').textContent = 'Checking model access with OpenAI…';
  try { updateConnection(await api('/api/connection', credentials)); notify('Model connected. Choose Live AI in the template lab when ready.'); }
  catch(error) { $('connection-message').textContent = error.message; }
  finally { credentials.api_key = ''; $('connect-button').disabled = false; }
});
$('disconnect-button').addEventListener('click', async () => {
  $('disconnect-button').disabled = true;
  try { updateConnection(await api('/api/disconnect', {})); $('api-key').value = ''; notify('Live AI disconnected for this server session.'); }
  catch(error) { notify(error.message, true); }
  finally { $('disconnect-button').disabled = false; }
});

function renderLibrary(documents) {
  $('library-count').textContent = `${documents.length} DOCUMENT${documents.length === 1 ? '' : 'S'}`;
  $('library-items').innerHTML = documents.length ? documents.map(d => `<article class="library-item"><div class="library-item-header"><h3>${escapeHtml(d.title)}</h3><label class="reference-switch"><input type="checkbox" data-document="${escapeHtml(d.id)}" aria-label="Include ${escapeHtml(d.title)} in retrieval" ${d.enabled ? 'checked' : ''}> Include</label></div><p>${d.characters.toLocaleString()} characters · ${d.chunks} passage${d.chunks === 1 ? '' : 's'} · ${d.enabled ? 'Used in retrieval' : 'Excluded from retrieval'}</p><p class="source-type">Content fingerprint: ${escapeHtml(d.sha256.slice(0,16))}…</p>${d.url ? `<a href="${escapeHtml(d.url)}" target="_blank" rel="noopener noreferrer">Source link ↗</a>` : ''}</article>`).join('') : '<p class="field-help">No imported references yet. Add your first text or Markdown reference using the form. The built-in notes are already available.</p>';
  $('library-items').querySelectorAll('[data-document]').forEach(input => input.addEventListener('change', async () => {
    const enabled = input.checked; input.disabled = true;
    try {
      const result = await api('/api/documents/state', {id:input.dataset.document, enabled});
      renderLibrary(result.documents); clearRetrieval();
      notify(enabled ? 'Reference included in future runs.' : 'Reference excluded from future runs. It remains saved locally.');
    } catch(error) { input.checked = !enabled; input.disabled = false; notify(error.message, true); }
  }));
}
function clearRetrieval() { $('retrieval-results').textContent = ''; $('retrieval-status').textContent = 'Library changed. Search again to inspect the current references.'; }
async function refreshLibrary() {
  const result = await api('/api/library');
  renderLibrary(result.documents);
  $('builtin-items').innerHTML = result.built_in.map(d => sourceCard(d)).join('');
}
$('reference-file').addEventListener('change', async () => {
  const file = $('reference-file').files[0];
  if (!file) return;
  try {
    if (!/\.(txt|md)$/i.test(file.name) || file.size > 600000) throw new Error('Choose a UTF-8 .txt or .md file, no larger than 600 KB.');
    const content = new TextDecoder('utf-8', {fatal:true}).decode(await file.arrayBuffer());
    if (content.length > 150000) throw new Error('This reference exceeds 150,000 characters. Import a relevant section instead.');
    $('reference-content').value = content;
    if (!$('reference-title').value.trim()) $('reference-title').value = file.name.replace(/\.(txt|md)$/i, '').slice(0,120);
    $('import-status').textContent = 'File loaded into the form. Review it, then click Import reference.';
  } catch(error) { $('reference-file').value = ''; $('import-status').textContent = error.message; }
});
$('import-form').addEventListener('submit', async event => {
  event.preventDefault(); $('import-button').disabled = true;
  try {
    const result = await api('/api/documents/import', {title:$('reference-title').value, url:$('reference-url').value, content:$('reference-content').value});
    renderLibrary(result.documents); clearRetrieval();
    $('import-status').textContent = result.duplicate ? 'This exact text is already in your library. No duplicate was added; check its Include setting.' : 'Reference imported. It is available to retrieval in future runs.';
    if (!result.duplicate) $('import-form').reset();
  } catch(error) { $('import-status').textContent = error.message; }
  finally { $('import-button').disabled = false; }
});
$('search-form').addEventListener('submit', async event => {
  event.preventDefault(); $('search-button').disabled = true;
  try {
    const result = await api('/api/retrieve', {query:$('reference-query').value});
    $('retrieval-results').innerHTML = result.documents.map(d => sourceCard(d, true)).join('');
    $('retrieval-status').textContent = `${result.documents.length} passages found · ${result.snapshot.chunk_count} searchable passages · library ${result.snapshot.sha256.slice(0,12)}. Scores rank text relevance; they are not confidence probabilities.`;
  } catch(error) { $('retrieval-status').textContent = error.message; }
  finally { $('search-button').disabled = false; }
});
api('/api/status').then(data => {
  if (!data.connection) throw new Error('An older VerifyNet server is still running. Restart the server to load this version.');
  statusData = data;
  $('server-state').textContent = 'Connected';
  updateConnection(data.connection);
  showSources(data.documents);
  $('run-benchmark').childNodes[0].nodeValue = 'Run 100 fixtures ';
  $('run-benchmark').closest('.benchmark-card').querySelector('p').textContent = '100 development and held-out fixtures cover IPv4, IPv6, multi-interface, VLAN, and OSPF tasks with malformed and incorrect configurations.';
}).catch(error => { $('server-state').textContent = 'Unavailable'; notify(error.message, true); });
refreshRouterStatus();

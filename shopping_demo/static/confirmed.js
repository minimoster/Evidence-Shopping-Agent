'use strict';
const $ = id => document.getElementById(id);
let csrf = '', current = null, trace = null, events = [], busy = false, initialized = false, draftDirty = false;
const labels = {idle:'未开始', needs_clarification:'需要澄清', awaiting_confirmation:'等待确认',
  confirmed:'已确认 · 可执行', running:'执行中', finished:'已结束', failed:'执行失败', proposal_failed:'提议失败'};
const issueNames = {clarify_explicit_CNY_ceiling:'请补充明确的人民币最高价。',
  clarify_unresolved_source:'该句子不在有限手写示例内，无法解释；请新建受支持的示例任务。',
  'unsupported_predicate:diving':'潜水功能不能由当前证据规则核验，禁止确认执行。',
  'unsupported_predicate:uninterpreted_query':'未解释的需求不能被省略。'};
const errors = {invalid_task_request:'请求已拒绝，请检查预算格式、当前修订和确认状态',
  csrf_required:'页面会话验证已失效，请刷新页面', session_required:'会话不存在，请刷新页面',
  trace_not_ready:'当前任务尚无可回放轨迹', trace_not_found_in_this_session:'该轨迹不属于当前任务或会话'};
async function request(path, body) {
  const options = {credentials:'same-origin'};
  if (body !== undefined) Object.assign(options, {method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token':csrf}, body:JSON.stringify(body)});
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(errors[data.error] || '请求失败，请检查当前页面状态');
  return data;
}
function text(id, value) { $(id).textContent = value == null ? '' : value; }
function json(id, value) { text(id, value ? JSON.stringify(value, null, 2) : ''); }
function updateButtons() {
  const status = current?.status;
  for (const id of ['propose','example','query','scenario']) $(id).disabled = busy;
  $('clarify').disabled = busy || draftDirty || status !== 'needs_clarification';
  $('ceiling').disabled = busy;
  $('accepted').disabled = busy || draftDirty || status !== 'awaiting_confirmation';
  $('confirm').disabled = busy || draftDirty || status !== 'awaiting_confirmation' || !$('accepted').checked;
  $('run').disabled = busy || draftDirty || status !== 'confirmed';
  text('input-warning', draftDirty ? '输入已编辑，请先新建任务；旧提议不能用于确认或执行这些新输入。' : '');
  for (const id of ['download','replay','prev','next','seek']) $(id).disabled = busy || !trace;
}
function show(state) {
  current = state;
  if (!initialized) {
    for (const value of state.finite_query_fixtures) { const option = new Option(value, value); $('example').add(option); }
    for (const [value, label] of Object.entries(state.scenarios)) $('scenario').add(new Option(label, value));
    $('query').value = state.review?.original_query || state.finite_query_fixtures[0];
    $('scenario').value = state.scenario || 'recovery'; initialized = true;
  }
  const review = state.review;
  text('status', labels[state.status] || state.status);
  text('original', review?.original_query || ''); text('candidate', review?.candidate_query || '尚无可确认的完整要求');
  json('proposal', review?.proposal); json('clarification-json', review?.budget_clarification);
  text('budget-source', review?.budget_clarification ? `用户新增明确上限：${review.budget_clarification.ceiling_cny} 元，替换原来的近似、名义或缺失预算解释；原提议仍保留。` : '尚未新增人工预算指令。');
  text('issues', (review?.issues || []).map(x => issueNames[x] || x).join('\n'));
  $('clarification').hidden = !(state.status === 'needs_clarification' && review.issues.includes('clarify_explicit_CNY_ceiling') && !review.budget_clarification);
  $('accepted').checked = state.status === 'confirmed' || state.status === 'finished';
  const outcome = state.c_outcome;
  text('outcome', outcome ? (outcome.purchase_outcome_unknown ? '执行结果未知，禁止自动重试。' :
    outcome.purchased ? 'C 组已完成一次合成商品模拟购买。' : 'C 组结束，未购买。') + ` 闸门拒绝 ${outcome.gate_rejections} 次。` : '确认并执行后显示。');
  $('arm-summary').replaceChildren();
  if (state.summary) for (const row of state.summary.rows) {
    const p = document.createElement('p'); p.textContent = `${row.arm}：${row.status} · ${row.purchased ? '模拟购买' : '未购买'} · 含提议调用 ${row.logical_model_calls}`;
    $('arm-summary').append(p);
  }
  text('counts', state.summary ? `当前任务离线传输 ${state.summary.physical_requests} 次；共享提议物理计一次、每组预算各计一次。不是历史任务总计。` : '');
  json('summary', state.summary); updateButtons();
}
function showEvent() {
  const i = Number($('seek').value); const event = events[i];
  text('position', events.length ? `${i + 1} / ${events.length}` : '');
  text('event-label', event?.label || ''); json('event', event?.value);
}
async function loadTrace() {
  trace = await request('/api/confirmed/trace?revision=' + encodeURIComponent(current.revision));
  const row = trace.rows.find(x => x.arm === 'C');
  events = [{label:'初始公开观察（原句和确认需求均保留）', value:row.trajectory.initial_result}];
  let gateIndex = 0;
  for (const step of row.trajectory.steps) {
    const gate = step.tool_name === 'buy_now' ? row.gate_events[gateIndex++] : null;
    events.push({label:`动作 ${step.tool_name}${gate ? (gate.executed === false ? ' · 闸门拒绝，未执行' : gate.executed === true ? ' · 已执行' : ' · 执行结果未知') : ''}`, value:{step, gate}});
  }
  $('seek').max = Math.max(0, events.length - 1); $('seek').value = 0; showEvent();
}
async function perform(action) {
  if (busy) return;
  busy = true; text('message',''); updateButtons();
  try { await action(); } catch (error) { text('message', `操作未完成：${error.message}。请刷新页面查看状态，不要重复提交执行；系统不会自动重试购买。`); }
  finally { busy = false; updateButtons(); }
}
function resetTrace() { trace = null; events = []; $('seek').value = 0; showEvent(); text('replay-status',''); }
function dirtyInput() { draftDirty = true; $('accepted').checked = false; updateButtons(); }
$('example').addEventListener('change', () => { $('query').value = $('example').value; dirtyInput(); });
$('query').addEventListener('input', dirtyInput);
$('scenario').addEventListener('change', dirtyInput);
$('accepted').addEventListener('change', updateButtons);
$('propose').addEventListener('click', () => perform(async () => {
  const state = await request('/api/confirmed/new', {query:$('query').value, scenario:$('scenario').value});
  resetTrace(); draftDirty = false; $('ceiling').value = ''; show(state);
}));
$('clarify').addEventListener('click', () => perform(async () => show(await request('/api/confirmed/clarify', {revision:current.revision, ceiling_cny:$('ceiling').value}))));
$('confirm').addEventListener('click', () => perform(async () => show(await request('/api/confirmed/confirm', {revision:current.revision, review_sha256:current.review.review_sha256, accepted:$('accepted').checked}))));
$('run').addEventListener('click', () => perform(async () => { show(await request('/api/confirmed/run', {revision:current.revision})); await loadTrace(); }));
$('replay').addEventListener('click', () => perform(async () => { const result = await request('/api/confirmed/replay', {revision:current.revision}); text('replay-status', `一致性通过：重算 ${result.gate_decisions_checked} 次闸门；没有执行动作。`); }));
$('seek').addEventListener('input', showEvent);
$('prev').addEventListener('click', () => { $('seek').value = Math.max(0, Number($('seek').value) - 1); showEvent(); });
$('next').addEventListener('click', () => { $('seek').value = Math.min(events.length - 1, Number($('seek').value) + 1); showEvent(); });
$('download').addEventListener('click', () => {
  if (!trace) return;
  const link = document.createElement('a'), url = URL.createObjectURL(new Blob([JSON.stringify(trace,null,2)], {type:'application/json'}));
  link.href = url; link.download = 'offline-confirmed-' + current.revision + '.json'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
});
perform(async () => { const session = await request('/api/session'); csrf = session.csrf; show(await request('/api/confirmed')); if (current.status === 'finished') await loadTrace(); });

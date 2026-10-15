"use strict";
const $ = id => document.getElementById(id);
let csrf = "", state = null, trace = null, busy = false, live = true;
const labels = {ready:"待运行",running:"运行中",success:"合成购买成功",blocked:"已阻止",failure:"执行失败"};
const reasons = {
  ready:"尚未执行工具。",step_completed:"工具已执行，观察已更新。",purchase_gate_blocked:"当前证据未通过核验，buy 未交给环境执行。",
  synthetic_fixture_purchase_only:"仅完成内存合成 fixture 的购买，没有真实交易。",policy_or_environment_error:"策略或合成环境发生异常，已停止。",
  initial_observation_unavailable:"初始公开观察不可用，已停止。",invalid_or_disallowed_tool:"工具不在许可范围内，已停止。",step_limit_exceeded:"达到停止上限，已停止。",
  query_not_supported:"query 不符合窄语法，未尝试购买。",no_visible_candidate:"没有满足已支持字段的公开候选商品。",requested_option_unavailable:"请求的选项不可见。",
  non_public_or_malformed_observation_rejected:"拒绝非公开或格式错误的观察，未执行购买。",
  real_purchase_execution_disabled:"此演示禁止执行非 fixture 购买。",fixture_purchase_not_confirmed:"未得到合成购买终态，未宣称成功。"
};
const gateReasons = {over_budget:"当前价格超过显式预算",price_unknown:"当前价格未知",budget_unknown:"预算未知",not_current_product_detail:"当前不是商品详情页",buy_action_not_currently_visible:"当前没有可见购买动作",intended_variant_mismatch:"欲购买变体与当前选择不一致",intended_asin_mismatch:"欲购买商品与当前观察不一致"};
function node(tag, text, cls) { const n=document.createElement(tag); if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n; }
async function api(path, body) {
  const options={credentials:"same-origin",cache:"no-store"};
  if(body!==undefined){options.method="POST";options.headers={"Content-Type":"application/json","X-CSRF-Token":csrf};options.body=JSON.stringify(body);}
  const response=await fetch(path,options);const data=await response.json();
  if(!response.ok)throw new Error(data.error||"request_failed");return data;
}
function lock(value){busy=value;for(const id of ["apply","run","step","reset","scenario","query"]){$(id).disabled=value;}}
async function operation(fn){if(busy)return;lock(true);$("message").textContent="";try{await fn();}catch(e){$("message").textContent="操作未完成："+e.message+"。如服务已重启，请刷新页面建立新会话。";}finally{lock(false);}}
async function refresh(next){state=next;trace=await api("/api/trace?trace_id="+encodeURIComponent(state.trace_id));$("seek").max=String(trace.events.length-1);if(live)$("seek").value=$("seek").max;render();}
async function ensureTask(){if(!state||$("query").value!==state.query||$("scenario").value!==state.scenario){await refresh(await api("/api/task",{query:$("query").value,scenario:$("scenario").value}));}}
function empty(parent,title,detail){const box=node("div",undefined,"empty");box.append(node("strong",title),node("span",detail));parent.append(box);}
function renderObservation(obs){
  const target=$("observation");target.replaceChildren();
  if(!obs||!obs.page_type){empty(target,"无公开观察","任务已安全停止。");return;}
  if(obs.page_type==="search_home"){empty(target,"合成商店 / 搜索首页","下一步脚本将根据显式品类发起 search。");return;}
  if(obs.page_type==="terminal"){empty(target,"合成购买完成 ✓","只更新此任务的内存状态，无付款、订单或发货。");return;}
  const products=obs.page_type==="search_results"?obs.products:[obs.product];
  if(!products.length){empty(target,"没有公开候选","可尝试文档中的耳机示例 query。");return;}
  for(const product of products){const card=node("div",undefined,"product");card.append(node("div","◉ )))","graphic"),node("h3",product.title),node("p",product.brand+" / "+product.category),node("p","合成商品编号 "+product.asin));
    if(obs.page_type==="product_detail"){
      const price=node("div",obs.selected_price==null?"价格未知":"¥ "+obs.selected_price,"price");price.append(node("small","当前所选变体"));card.append(price);
      for(const [axis,values] of Object.entries(obs.available_options)){const row=node("div");for(const value of values)row.append(node("span",axis+" · "+value,"option"+(obs.selected_options[axis]===value?" selected":"")));card.append(row);}
      card.append(node("p",product.key_attributes.join(" · ")));
    }else{card.append(node("p","搜索摘要价格区间："+product.price+"（不能用于购买授权）"));}target.append(card);}
}
function renderGate(gate){const target=$("gate");target.replaceChildren();if(!gate){empty(target,"尚未提交 buy","ScriptedPolicy 提交 buy 后，这里才显示真实 prototype gate 的结果。");return;}
  target.append(node("div",gate.allowed?"核验通过 ✓":"阻止购买 ⊘","gatebadge "+(gate.allowed?"allowed":"blocked")),node("p",gate.allowed?"此授权只绑定当前 revision、商品、变体和价格。":"任何未知、冲突或不匹配都不会继续执行 buy。","hint"));
  const dl=node("dl",undefined,"proofdl");for(const [label,value] of [["证据 revision",gate.revision],["商品编号",gate.asin||"未知"],["当前价格",gate.price===null?"未知":"CNY "+gate.price],["显式预算",gate.budget===null?"未知":"CNY "+gate.budget],["当前变体",Object.entries(gate.variant).map(([k,v])=>k+":"+v).join(", ")||"无"]]){dl.append(node("dt",label),node("dd",String(value)));}target.append(dl);
  if(gate.reasons.length){const list=node("ul",undefined,"reasonlist");for(const reason of gate.reasons)list.append(node("li",gateReasons[reason]||reason));target.append(list);}
  if(gate.evidence.length)target.append(node("p","规格与公开证据来源","hint"));for(const evidence of gate.evidence){const fact=node("div",evidence.key+" = "+evidence.value,"fact");fact.append(node("small",evidence.source_path+" · revision "+evidence.revision));target.append(fact);}
}
function render(){if(!state||!trace)return;const index=Math.min(Number($("seek").value),trace.events.length-1);const event=trace.events[index];$("status").className="status "+(live?state.status:event.status);$("status").textContent=labels[live?state.status:event.status]||event.status;$("steps").textContent="STEP "+event.step+" / "+state.max_steps;$("reason").textContent=reasons[live?state.reason:event.reason]||event.reason;$("taskid").textContent=state.task_id;$("traceid").textContent=state.trace_id;$("viewmode").textContent=live?"当前":"历史回放";$("position").textContent=(index+1)+" / "+trace.events.length;renderObservation(event.observation);renderGate(event.gate);$("eventjson").textContent=JSON.stringify(event,null,2);$("timeline").replaceChildren();for(const item of trace.events){const li=node("li"),button=node("button",item.action?item.action.tool:"init",item.index===index?"selected":"");button.addEventListener("click",()=>{live=false;$("seek").value=String(item.index);render();});li.append(button);$("timeline").append(li);}$("prev").disabled=index===0;$("next").disabled=index===trace.events.length-1;}
$("apply").addEventListener("click",()=>operation(async()=>{live=true;await refresh(await api("/api/task",{query:$("query").value,scenario:$("scenario").value}));}));
for(const id of ["run","step"]){$(id).addEventListener("click",()=>operation(async()=>{live=true;await ensureTask();await refresh(await api("/api/"+id,{}));}));}
$("reset").addEventListener("click",()=>operation(async()=>{live=true;await refresh(await api("/api/reset",{}));$("query").value=state.query;$("scenario").value=state.scenario;}));
$("seek").addEventListener("input",()=>{live=false;render();});for(const [id,delta] of [["prev",-1],["next",1]]){$(id).addEventListener("click",()=>{live=false;$("seek").value=String(Number($("seek").value)+delta);render();});}$("live").addEventListener("click",()=>{live=true;$("seek").value=$("seek").max;render();});
$("download").addEventListener("click",()=>{if(!trace)return;const url=URL.createObjectURL(new Blob([JSON.stringify(trace,null,2)],{type:"application/json"}));const a=node("a");a.href=url;a.download="offline-shopping-"+state.trace_id+".json";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
operation(async()=>{const data=await api("/api/session");csrf=data.csrf;for(const [value,label] of Object.entries(data.scenarios)){const option=node("option",label);option.value=value;$("scenario").append(option);}$("query").value=data.state.query;$("scenario").value=data.state.scenario;await refresh(data.state);});

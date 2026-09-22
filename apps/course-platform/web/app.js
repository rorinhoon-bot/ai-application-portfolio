"use strict";
const $ = (selector) => document.querySelector(selector);
const icon = (name) => {
  const paths = {plus:'<path d="M12 5v14M5 12h14"/>',home:'<path d="m3 10 9-7 9 7v10H3V10Z"/><path d="M9 20v-7h6v7"/>',tasks:'<rect x="4" y="3" width="16" height="18" rx="3"/><path d="M8 8h8M8 12h8M8 16h5"/>',book:'<path d="M12 5c-3-2-7-2-10-1v15c3-1 7-1 10 1 3-2 7-2 10-1V4c-3-1-7-1-10 1Zm0 0v15"/>',chart:'<path d="M4 3v17h17M8 15v-4m5 4V7m5 8V4"/>',shield:'<path d="m12 2 8 3v6c0 5-4 8-8 11-4-3-8-6-8-11V5l8-3Z"/><path d="m8 11 3 3 5-6"/>',panel:'<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M9 4v16"/>',file:'<path d="M14 2H5v20h14V7l-5-5Zm0 0v6h5M8 12h8M8 16h6"/>',search:'<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>',arrow:'<path d="M5 12h14m-5-5 5 5-5 5"/>',spark:'<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3Z"/>',check:'<path d="m5 12 4 4L19 6"/>',clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',folder:'<path d="M3 6h7l2 2h9v12H3V6Z"/>'};
  return `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name]||paths.file}</svg>`;
};
document.querySelectorAll('[data-icon]').forEach(node=>node.innerHTML=icon(node.dataset.icon));
const escape = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const uuid = () => crypto.randomUUID().replaceAll("-", "");
const state = {boot:null, tasks:[], task:null, tab:"report", filter:"", status:"all", archived:false, route:"", loading:false, decision:null};
const secure = () => Boolean(state.boot?.auth_required);
const role = () => state.boot?.identity?.role;
const researcher = () => !secure() || role()==='researcher';
const reviewer = () => !secure() || ['reviewer','admin'].includes(role());
const createEntry = () => secure() ? '<a class="button primary" href="#projects">创建研究项目</a>' : button('新建研究任务','create');
const labels = {INITIALIZING:"正在准备", NEEDS_HUMAN:"待确认范围", REPORT_NEEDS_HUMAN:"待审核报告", COMPLETED:"已交付", REJECTED:"已拒绝", CANCELLED:"已取消", FAILED:"运行失败"};
const actionLabels = {approve:"批准并继续", reject:"拒绝当前任务", cancel:"取消任务", recover:"恢复任务状态"};
const time = value => value ? new Date(value).toLocaleString("zh-CN", {hour12:false}) : "—";
const badge = item => `<span class="badge ${item.busy ? "running" : item.status === "COMPLETED" ? "success" : item.status?.includes("HUMAN") ? "wait" : ["FAILED","REJECTED","CANCELLED"].includes(item.status) ? "fail" : ""}">${item.busy ? "处理中" : escape(item.decision_outcome === "rejected" ? "已拒绝" : labels[item.status] || item.status)}</span>`;
const button = (label, action, extra="", style="primary") => `<button class="button ${style}" data-action="${action}" ${extra}>${label}</button>`;
const notice = (message, type="") => `<div class="notice ${type}">${escape(message)}</div>`;
function toast(message) { $("#toast").textContent=message; $("#toast").hidden=false; clearTimeout(toast.timer); toast.timer=setTimeout(()=>$("#toast").hidden=true,5000); }
async function api(path, payload) {
  const response = await fetch(path, payload === undefined ? {cache:"no-store"} : {method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":state.boot.csrf_token},body:JSON.stringify(payload)});
  const data = await response.json();
  if (!response.ok) {
    if(data.error?.code==='UNAUTHENTICATED' && secure()){state.boot=null;await authStart();}
    throw new Error(`${data.error?.message || "请求失败"} (${data.error?.code || response.status})`);
  }
  return data;
}
function heading(title, description, actions="") { return `<div class="page-heading"><div><h1>${escape(title)}</h1><p class="muted">${escape(description)}</p></div><div class="heading-actions">${actions}</div></div>`; }
function table(tasks, empty="还没有研究任务") {
  if (!tasks.length) return `<div class="empty"><div class="empty-symbol">${icon("file")}</div><h3>${empty}</h3><p>从一个问题开始，保留每一步证据和决定。</p>${researcher()?createEntry():''}</div>`;
  return `<div class="table-wrap"><table><thead><tr><th>研究任务</th><th>当前状态</th><th>证据</th><th>最近更新</th><th></th></tr></thead><tbody>${tasks.map(t=>`<tr><td><a class="task-name" href="#task/${t.id}">${escape(t.title)}</a><div class="task-question">${escape(t.question)}</div></td><td>${badge(t)}</td><td>${t.evidence_count} 条</td><td class="muted">${time(t.updated_at)}</td><td><a href="#task/${t.id}" aria-label="查看${escape(t.title)}">查看 ↗</a></td></tr>`).join("")}</tbody></table></div>`;
}
function dashboard() {
  const tasks=state.tasks.filter(t=>!t.archived), pending=tasks.filter(t=>!t.busy && t.status.includes("HUMAN"));
  $("#content").innerHTML=(secure()?`<section class="research-start"><div class="start-symbol">${icon('shield')}</div><h1>${role()==='researcher'?'从可信资料开始研究。':role()==='admin'?'查看运行与权限审计。':'核对范围，留下审核依据。'}</h1><p>当前身份：${escape(state.boot.identity.username)} · ${escape(({researcher:'研究者',reviewer:'审核者',admin:'管理员'})[role()])}。每次决定绑定项目与请求记录。</p>${researcher()?'<a class="button primary" href="#projects">创建研究项目</a>':role()==='admin'?'<a class="button primary" href="#security">查看权限审计</a>':'<a class="button primary" href="#tasks">查看待审任务</a>'}</section>`:`<section class="research-start"><div class="start-symbol">${icon("spark")}</div><h1>让每一次研究，有据可循。</h1><p>从一个问题出发，在资料、证据与判断之间建立联系。</p><div class="question-composer"><label class="sr-only" for="quick-question">想研究什么</label><textarea id="quick-question" maxlength="500" rows="2" placeholder="描述你的研究问题，或从下面的示例开始…"></textarea><div class="composer-bottom"><span>${icon("book")} 固定方案资料集 <span class="quiet-dot"></span> 离线模式</span>${button(`开始研究 ${icon("arrow")}`,"start-question")}</div></div><div class="suggestions"><span>试试研究</span><button data-template="0">工具调用方案对比</button><button data-template="1">人工审批如何设计</button><button data-template="2">故障恢复与交付</button></div><p class="scope-caption">两个原创方案 · 六段固定资料 · 自定义问题不会扩展资料范围</p></section>`)+
    `<div class="stats-row">${[["tasks","研究任务",tasks.length,"当前工作空间"],["clock","待我确认",pending.length,"研究范围或报告"],["check","已完成交付",tasks.filter(t=>t.status==="COMPLETED").length,"保留完整研究记录"],["shield","真实模型调用",0,"本次运行不产生费用"]].map(([symbol,label,value,sub])=>`<div class="stat"><span class="stat-label">${icon(symbol)}${label}</span><strong>${value}</strong><small>${sub}</small></div>`).join("")}</div>`+
    (pending.length?notice(`有 ${pending.length} 个任务等待确认。打开任务后检查范围或报告。`,"warning"):"")+
    `<section class="panel recent-panel"><div class="panel-heading"><div><h2>最近的研究</h2><p class="muted">继续上次的思考，或开启新的探索。</p></div><a class="text-link" href="#tasks">查看全部 ${icon("arrow")}</a></div>${table(tasks.slice(0,6))}</section><div class="workspace-links"><a href="#knowledge">${icon("book")}<span><strong>资料库</strong><small>查看原始资料与来源</small></span>${icon("arrow")}</a><a href="#evaluations">${icon("chart")}<span><strong>评估与边界</strong><small>了解已验证的能力</small></span>${icon("arrow")}</a></div>`;
}
function taskList() {
  $("#content").innerHTML=heading("研究任务","集中查看进度、审批和交付记录。",researcher()?createEntry():'')+
    `<section class="panel"><div class="filters"><label class="search-field"><span class="sr-only">搜索任务</span><input id="task-search" type="search" value="${escape(state.filter)}" placeholder="搜索名称或研究问题"></label><label><span class="sr-only">任务状态</span><select id="status-filter"><option value="all">全部状态</option>${Object.entries(labels).map(([k,v])=>`<option value="${k}" ${state.status===k?"selected":""}>${v}</option>`).join("")}</select></label><label class="checkbox"><input id="archive-filter" type="checkbox" ${state.archived?"checked":""}> 包含归档</label></div><div id="task-table"></div></section>`;
  filterTasks();
}
function filterTasks(){ $("#task-table").innerHTML=table(state.tasks.filter(t=>(state.archived||!t.archived)&&(state.status==="all"||(t.decision_outcome==="rejected"?"REJECTED":t.status)===state.status)&&`${t.title} ${t.question}`.toLowerCase().includes(state.filter.toLowerCase())),"没有符合条件的任务"); }
function structured(value) {
  if(value === null || value === undefined) return `<span class="muted">尚未产生</span>`;
  if(Array.isArray(value)) return value.length ? `<ol>${value.map(v=>`<li>${structured(v)}</li>`).join("")}</ol>` : `<span class="muted">无</span>`;
  if(typeof value === "object") return `<dl>${Object.entries(value).map(([k,v])=>`<dt>${escape(({summary:"摘要",recommendation:"建议",candidate_id:"候选方案",dimension:"评估维度",claim:"结论",evidence_ids:"证据编号",limitations:"限制",title:"标题",answer:"回答",comparison:"方案对比",citations:"引用",rationale:"依据",findings:"发现",risks:"风险",cells:"比较条目",conclusion:"结论"})[k]||k)}</dt><dd>${structured(v)}</dd>`).join("")}</dl>`;
  return `<span>${escape(value)}</span>`;
}
const dimension = value => ({"tool-calling":"工具调用","human-approval":"人工审批","recovery":"故障恢复"}[value]||value);
function requestView(request) {
  if(!request)return "";
  return `<article class="report-content"><h2>研究范围</h2><p>${escape(request.research_question)}</p><h3>比较方案</h3><ul>${(request.candidates||[]).map(c=>`<li><strong>${escape(c.name)}</strong>：${escape(c.scope_note)}</li>`).join("")}</ul><h3>关注维度</h3><ul>${(request.dimensions||[]).map(d=>`<li>${escape(dimension(d.dimension_id))}：${escape(d.question)}</li>`).join("")}</ul><h3>约束条件</h3><ul>${(request.hard_constraints||[]).map(c=>`<li>${escape(c)}</li>`).join("")}</ul><details><summary>查看完整范围合同</summary>${structured(request)}</details></article>`;
}
function reportView(report) {
  return `<article class="report-content"><h2>研究摘要</h2><p>${escape(report.executive_summary||"暂无摘要")}</p><h3>建议与限制</h3><p>建议方案：<strong>${escape(report.recommendation||"暂不作推荐")}</strong></p><ul>${(report.limitations||[]).map(l=>`<li>${escape(l)}</li>`).join("")}</ul><h2>逐项证据比较</h2>${(report.evidence_cells||[]).map(c=>`<section class="evidence-block"><div class="evidence-meta">${escape(c.candidate_id)} · ${escape(dimension(c.dimension_id))}</div><h3>${escape(c.claim)}</h3><p class="muted">${escape(c.caveat)}</p><small>依据：${escape((c.evidence_ids||[]).join(" / "))}</small></section>`).join("")}<details><summary>完整报告合同与复核字段</summary>${structured(report)}</details></article>`;
}
function evidenceView(e,i) {
  return `<article class="evidence-block"><div class="evidence-meta">证据 ${i+1} · ${escape(e.candidate_id)} · ${escape(dimension(e.dimension_id||e.section_id))}</div><h3>${escape(e.evidence_id)}</h3><p>${escape(e.excerpt)}</p><p class="muted">来源：${escape(e.source_id)} / ${escape(e.locator)}</p><details><summary>绑定与完整来源信息</summary><div class="report-content">${structured(e)}</div></details></article>`;
}
function taskDetail(task) {
  state.task=task; const s=task.state, waiting=!task.busy&&["NEEDS_HUMAN","REPORT_NEEDS_HUMAN"].includes(task.status), complete=task.status==="COMPLETED";
  let actions=task.execution?`<a class="button secondary" href="#project/${escape(task.execution.project_id)}">返回冻结项目</a>`:secure()?'':button("复制任务","copy","", "secondary");
  if(complete&&!task.busy) actions+=button("下载交付包","download");
  const gate=task.status==="NEEDS_HUMAN"?"确认研究范围":"审核当前报告";
  $("#content").innerHTML=`<a class="back-link" href="#tasks">← 返回任务列表</a>`+heading(task.title,task.question,actions)+
    (task.last_error?notice(`上次操作未完成：${task.last_error}。原审批和工作流记录保留，可尝试恢复。`,"error"):"")+
    (task.execution?`<div class="execution-scope"><p>来自冻结项目 · 脚本模型只说明离线机制，不证明真实内容质量。</p><dl><div><dt>范围指纹</dt><dd><code>${escape(task.execution.contract_hash)}</code></dd></div><div><dt>执行指纹</dt><dd><code>${escape(task.execution.execution_hash)}</code></dd></div></dl></div>`:"")+
    `<div class="task-process">${["范围确认","证据与分析","报告审核","报告交付"].map((v,i)=>`<div class="process-step ${complete?"done":task.status==="REPORT_NEEDS_HUMAN"?(i<2?"done":i===2?"current":""):i===0?"current":""}"><span class="step-circle">${i+1}</span><strong>${v}</strong></div>`).join("")}</div>`+
    `<div class="detail-grid"><div><section class="panel"><div class="tabs" role="tablist" aria-label="任务详情">${[["report","研究报告"],["evidence",`证据 ${task.evidence_count}`],["audit","操作审计"]].map(([k,v])=>`<button role="tab" aria-selected="${state.tab===k}" data-tab="${k}">${v}</button>`).join("")}</div><div id="detail-body" class="panel-body"></div></section></div><aside><section class="decision-panel"><span class="decision-label">当前进度</span><div>${badge(task)}</div><h2>${task.busy?"正在执行离线工作流":waiting?gate:complete?"交付已准备好":"任务记录已保留"}</h2><p>${task.busy?"可以离开本页，后台继续处理。":waiting?"请检查左侧内容，明确记录本次决定。":complete?"下载包包含报告、证据绑定和工具审计，下载前自动校验。":"恢复只读取或继续原流程，不会绕过审批。"}</p>${waiting&&reviewer()?button("批准并继续","approve")+button("拒绝","reject","","secondary"):""}${waiting&&researcher()?button("取消任务","cancel","","secondary"):""}${researcher()&&task.execution&&task.status==="REPORT_NEEDS_HUMAN"&&!task.busy&&(s.human_revision_count||0)<2?button("修订摘要与限制","revise","","secondary"):""}${researcher()&&!task.busy?button("检查并恢复状态","recover","","secondary"):""}</section><section class="panel"><div class="panel-heading"><h2>运行信息</h2></div><div class="panel-body fact-grid">${[["模型模式","固定脚本 · 零费用"],["证据条数",task.evidence_count],["脚本模型调用",s.model_call_count??0],["MCP 工具调用",(s.tool_events||[]).length],["人工修订",s.human_revision_count??0],["创建时间",time(task.created_at)]].map(([k,v])=>`<div class="fact"><span>${k}</span><strong>${v}</strong></div>`).join("")}<div class="fact"><span>运行编号</span><code class="hash">${escape(s.run_id||"准备中")}</code></div></div></section>${researcher()&&!task.busy?button(task.archived?"取消归档":"归档任务","archive","","secondary"):""}</aside></div>`;
  renderTab();
}
function renderTab() {
  const task=state.task,s=task.state; let html="";
  if(state.tab==="report") html=s.report?notice("此报告由固定脚本模型生成，用于核查工作流；不代表真实模型内容质量通过。","warning")+reportView(s.report):
    `<div class="empty"><h3>${task.busy?"任务正在处理中":task.status==="NEEDS_HUMAN"?"研究范围待确认":"报告尚未生成"}</h3><p>范围批准后将检索${task.execution?"冻结项目资料":"固定示例资料"}，通过 MCP 工具查证并生成报告。</p></div>`+requestView(s.request);
  if(state.tab==="evidence") html=(s.evidence||[]).length?(s.evidence||[]).map(evidenceView).join(""):`<div class="empty"><h3>证据尚未生成</h3><p>范围确认后再执行检索与工具调用。</p></div>`;
  if(state.tab==="audit") html=notice("网页操作说明关联本地任务与请求编号；工作流审批和 MCP 回执由各自模块保存。")+
    (task.events||[]).map(e=>`<div class="audit-item"><span class="audit-dot"></span><div><strong>${escape(({operation_requested:"操作者提交决定",state_updated:"任务状态已更新",operation_failed:"操作未完成",process_interrupted:"处理曾被中断",archived:"归档状态变更"})[e.kind]||e.kind)}</strong><time>${time(e.created_at)}</time><div class="report-content">${structured(e.details)}</div><small class="hash">${escape(e.request_id||"")}</small></div></div>`).join("")+
    `<details><summary>工作流审批记录（${(s.approvals||[]).length}）</summary><div class="report-content">${structured(s.approvals)}</div></details><details><summary>MCP 工具调用（${(s.tool_events||[]).length}）</summary><div class="report-content">${structured(s.tool_events)}</div></details>`;
  $("#detail-body").innerHTML=html;
  document.querySelectorAll("[data-tab]").forEach(b=>b.setAttribute("aria-selected",b.dataset.tab===state.tab));
}
async function knowledge() {
  const data=await api("/api/knowledge"); if(state.route!=="knowledge")return;
  state.records=data.records; state.corpusHash=data.corpus_hash; state.knowledgeSource=state.knowledgeSource||"all"; state.knowledgeQuery=""; state.readerTab="text";
  $("#content").innerHTML=heading("知识资料","每一条结论，都从可靠的来源开始。",secure()?'':button(`${icon("plus")} 新建研究`,"create"))+
    `<div class="knowledge-overview"><div class="collection-symbol">${icon("book")}</div><div><h2>AI 方案研究资料集 <span class="subtle-badge">固定资料</span></h2><p>围绕工具调用、人工审批与故障恢复，比较两种原创设计。</p><div class="collection-meta"><span>${icon("folder")} 2 个来源</span><span>${icon("file")} ${data.records.length} 段资料</span><span>${icon("shield")} 来源指纹可核验</span></div></div></div>`+
    `<section class="library"><div class="library-toolbar"><div class="source-tabs" role="group" aria-label="按来源筛选"><button data-source="all">全部资料</button><button data-source="graph-plan">Graph 方案</button><button data-source="chain-plan">Chain 方案</button></div><label class="search-input">${icon("search")}<span class="sr-only">搜索知识资料</span><input id="knowledge-search" type="search" placeholder="搜索资料内容…"></label></div><div class="library-split"><aside class="document-list"><div class="list-caption"><span>资料目录</span><span id="record-count"></span></div><div id="knowledge-records"></div></aside><article id="knowledge-reader" class="document-reader" aria-label="资料阅读区"></article></div></section><p class="library-note">${icon("shield")} 当前为原创合成资料。搜索仅过滤本地文本，不代表真实检索质量。</p>`;
  filterKnowledge("");
}
function filterKnowledge(query) {
  state.knowledgeQuery=query;
  const records=state.records.filter(r=>(state.knowledgeSource==="all"||r.candidate_id===state.knowledgeSource)&&`${r.title} ${r.text} ${dimension(r.section_id)}`.toLowerCase().includes(query.toLowerCase()));
  if(!records.some(r=>r.record_id===state.selectedRecord))state.selectedRecord=records[0]?.record_id;
  $("#record-count").textContent=`${records.length} 段`;
  document.querySelectorAll('[data-source]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.source===state.knowledgeSource));
  $("#knowledge-records").innerHTML=records.length?records.map(r=>`<button class="document-item" data-record="${escape(r.record_id)}" aria-pressed="${state.selectedRecord===r.record_id}"><span class="document-icon ${r.candidate_id==="chain-plan"?"chain":""}">${icon("file")}</span><span class="document-info"><strong>${escape(dimension(r.section_id))}</strong><span>${r.candidate_id==="graph-plan"?"Graph":"Chain"} 方案</span><small>${escape(r.text)}</small></span>${icon("arrow")}</button>`).join(""):`<div class="list-empty">${icon("search")}<p>没有匹配的资料</p><small>试试其他关键词或来源</small></div>`;
  renderReader();
}
function renderReader() {
  const r=state.records.find(r=>r.record_id===state.selectedRecord);
  if(!r){$("#knowledge-reader").innerHTML='<div class="empty"><h3>未找到资料</h3><p>清空搜索条件，或切换到全部资料。</p></div>';return;}
  $("#knowledge-reader").innerHTML=`<div class="reader-toolbar"><span>${icon("file")}${escape(r.source_file)}</span><span class="subtle-badge">只读</span></div><div class="reader-content"><div class="reader-category">${r.candidate_id==="graph-plan"?"Graph":"Chain"} 方案 <span>/</span> 研究资料</div><h2>${escape(dimension(r.section_id))}</h2><p class="reader-subtitle">${escape(r.title)}</p><div class="reader-tabs" role="group" aria-label="资料内容视图"><button data-reader-tab="text" aria-pressed="${state.readerTab==="text"}">原文摘录</button><button data-reader-tab="source" aria-pressed="${state.readerTab==="source"}">来源与指纹</button></div>${state.readerTab==="text"?`<div class="excerpt-label">原文 · English</div><blockquote>${escape(r.text)}</blockquote><div class="reference-location"><span>${icon("book")} 引用位置</span><code>${escape(r.source_file)}#${escape(r.section_id)}</code></div><div class="reader-boundary">${icon("shield")}<p>这是用于验证工作流的原创设计资料，描述的是方案设计，不代表实测性能。</p></div>`:`<dl class="source-facts"><dt>来源文件</dt><dd>${escape(r.source_file)}</dd><dt>段落编号</dt><dd>${escape(r.record_id)}</dd><dt>内容 SHA-256</dt><dd class="hash">${escape(r.content_sha256)}</dd><dt>来源 SHA-256</dt><dd class="hash">${escape(r.source_sha256)}</dd><dt>资料集 SHA-256</dt><dd class="hash">${escape(state.corpusHash)}</dd></dl>`}</div><div class="reader-footer"><span>${icon("check")} 来自已解析的固定资料集</span><a href="#dashboard">开始研究 ${icon("arrow")}</a></div>`;
}
async function evaluations() { const data=await api("/api/evaluations"); if(state.route!=="evaluations")return; $("#content").innerHTML=heading("评估与说明","分别检查工程可靠性、工具安全和内容质量。")+notice(data.limits,"warning")+`<section class="panel"><div class="panel-heading"><h2>已有工程验证</h2><span class="muted">历史发布基线</span></div><div class="panel-body"><p>${escape(data.label)}</p><div class="eval-grid">${data.results.map(r=>`<div class="eval-item"><span>${escape(r.name)}</span><strong>${escape(r.summary.join(" · "))}</strong><small>${r.exit_code===0?"该次验证通过":"该次验证失败"}</small></div>`).join("")}</div><p class="hash">证据：${escape(data.provenance)}</p></div></section><section class="panel"><div class="panel-heading"><h2>课设可复用边界</h2></div><div class="panel-body report-content"><p>当前交付：单机界面、冻结项目、双审批、P1分词、P2离线脚本研究、P3只读MCP、报告修订和验证后下载。</p><p>${secure()?'G3 本机身份模式已增加研究者/审核者隔离；只验证应用层会话与对象权限。':'项目资料仅在明确冻结的版本中执行；多用户权限仍未验证。'} P1向量检索、真实内容质量与公开部署仍未验证。</p><p>P2 真实模型内容验收未通过；预算与调用容量已封顶。界面审批是演示工作流决定，不是内容质量认证。</p><p>${escape(data.current_app)}</p></div></section>`; }
async function securityPage(){
  const data=await api('/api/security/audit');if(state.route!=='security')return;
  $('#content').innerHTML=heading('权限审计','仅管理员可读。记录身份、资源与允许或拒绝结果，不保存密码和会话令牌。')+
    `<section class="panel panel-body"><p>最近 ${data.events.length} 条操作，最多显示 ${data.limit} 条。当前权限仅在本机状态目录生效。</p><div class="table-wrap"><table><thead><tr><th>时间</th><th>身份</th><th>动作</th><th>资源</th><th>结果</th></tr></thead><tbody>${data.events.map(e=>`<tr><td>${time(e.created_at*1000)}</td><td>${escape(e.username||'匿名')}<br><code>${escape(e.user_id||'—')}</code></td><td>${escape(e.action)}</td><td><code class="hash">${escape(e.resource)}</code></td><td>${escape(e.outcome)}</td></tr>`).join('')}</tbody></table></div></section>`;
}
async function route(silent=false) {
  const key=location.hash.slice(1)||"dashboard"; const changed=state.route!==key; state.route=key;
  if(changed)state.tab="report";
  const section=key.startsWith("task/")?"tasks":key.startsWith("project/")?"projects":key;
  document.querySelectorAll("[data-nav]").forEach(n=>n.setAttribute("aria-current",n.dataset.nav===section?"page":"false"));
  $("#breadcrumb").textContent="我的空间 / "+({dashboard:"工作台",tasks:"研究任务",projects:"研究项目",library:"项目资料",knowledge:"离线示例",evaluations:"评估与说明",security:"权限审计"}[section]||"任务详情");
  $("#content").dataset.page=section;
  if(!silent)$("#content").innerHTML='<div class="loading"><span class="spinner"></span> 正在读取…</div>';
  try {
    if(["dashboard","tasks"].includes(key)) { const data=await api("/api/tasks"); if(state.route!==key)return; state.tasks=data.tasks; key==="dashboard"?dashboard():silent&&$("#task-table")?filterTasks():taskList(); }
    else if(/^task\/task-[a-f0-9]{32}$/.test(key)) {const task=await api("/api/tasks/"+key.split("/")[1]); if(state.route===key)taskDetail(task);}
    else if(key==="library")await libraryPage();
    else if(key==="projects")await projectsPage();
    else if(/^project\/project-[a-f0-9]{32}$/.test(key))await projectPage(key.split('/')[1]);
    else if(key==="knowledge")await knowledge();
    else if(key==="evaluations")await evaluations();
    else if(key==="security")await securityPage();
    else $("#content").innerHTML=heading("页面不存在","请通过左侧导航继续。");
  } catch(error) { if(state.route===key)$("#content").innerHTML=notice(error.message,"error")+button("重新读取","refresh"); }
}
function createDialog(copy=false) {
  const form=$("#create-form");form.reset();form.elements.title.value=copy?state.task.title+"（副本）":state.boot.default_title;form.elements.question.value=copy?state.task.question:state.boot.default_question;form.dataset.request=uuid();$("#create-error").textContent="";$("#create-dialog").showModal();
}
function decisionDialog(action) {
  const task=state.task; state.decision={task:task.id,action,expected_hash:task.status==="NEEDS_HUMAN"?task.state.request_hash:task.state.report_hash||"",request_id:uuid()};
  $("#decision-form").reset(); $("#decision-title").textContent=actionLabels[action];$("#decision-submit").textContent=actionLabels[action];
  $("#decision-description").textContent=action==="recover"?"检查原 checkpoint 与审计，继续未完成的步骤。仍需遵守原审批关卡。":action==="cancel"?"取消当前任务，保留已有记录，不再继续研究或交付。":action==="reject"?"拒绝当前范围或报告，记录拒绝依据并停止继续交付。":task.status==="NEEDS_HUMAN"?`本次决定针对研究范围。批准后开始${task.execution?"冻结项目资料":"固定资料"}检索与脚本分析。`:"本次决定针对当前报告版本。批准后生成可验证交付包。";
  $("#decision-hash").textContent=state.decision.expected_hash||"恢复原运行";$("#decision-error").textContent="";$("#decision-dialog").showModal();
}
document.addEventListener("click",async event=>{
  if(event.target.closest(".skip-link")){event.preventDefault();$("#content").focus();return;}
  const close=event.target.closest("[data-close]");if(close){close.closest("dialog").close();return;}
  const tab=event.target.closest("[data-tab]");if(tab){state.tab=tab.dataset.tab;renderTab();return;}
  const source=event.target.closest('[data-source]');if(source){state.knowledgeSource=source.dataset.source;filterKnowledge(state.knowledgeQuery);return;}
  const record=event.target.closest('[data-record]');if(record){state.selectedRecord=record.dataset.record;state.readerTab="text";filterKnowledge(state.knowledgeQuery);document.querySelectorAll("[data-record]").forEach(b=>{if(b.dataset.record===state.selectedRecord)b.focus({preventScroll:true});});return;}
  const readerTab=event.target.closest('[data-reader-tab]');if(readerTab){state.readerTab=readerTab.dataset.readerTab;renderReader();document.querySelectorAll("[data-reader-tab]").forEach(b=>{if(b.dataset.readerTab===state.readerTab)b.focus({preventScroll:true});});return;}
  const template=event.target.closest('[data-template]');if(template){$("#quick-question").value=["比较 graph-plan 与 chain-plan 的工具调用设计，说明证据与限制。","比较 graph-plan 与 chain-plan 的人工审批机制，说明如何限制未经批准的交付。","比较 graph-plan 与 chain-plan 的故障恢复与幂等交付设计，说明尚未验证的部分。"][Number(template.dataset.template)];$("#quick-question").focus();return;}
  const element=event.target.closest("[data-action]");if(!element)return; const action=element.dataset.action;
  try {
    if(action==="create"||action==="copy")return createDialog(action==="copy");
    if(action==="revise"){
      const form=$("#revision-form");form.reset();form.dataset.request=uuid();form.dataset.task=state.task.id;
      form.dataset.hash=state.task.state.report_hash;form.elements.summary.value=state.task.state.report.executive_summary;
      form.elements.limitations.value=(state.task.state.report.limitations||[]).slice(0,8).join("\n");
      $("#revision-error").textContent="";$("#revision-dialog").showModal();return;
    }
    if(action==="start-question"){const question=$("#quick-question").value.trim();createDialog();if(question)$("#create-form").elements.question.value=question;return;}
    if(actionLabels[action])return decisionDialog(action);
    if(action==="refresh")return route();
    element.disabled=true;
    if(action==="archive"){await api(`/api/tasks/${state.task.id}/archive`,{archived:!state.task.archived});toast("归档状态已更新");await route(true);}
    if(action==="download") {const response=await fetch(`/api/tasks/${state.task.id}/download`);if(!response.ok){const data=await response.json();throw Error(data.error.message);}const url=URL.createObjectURL(await response.blob());const a=document.createElement("a");a.href=url;a.download="research-delivery.zip";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast("交付包校验通过，已开始下载");}
  }catch(error){toast(error.message);}finally{element.disabled=false;}
});
document.addEventListener("input",event=>{if(event.target.id==="task-search"){state.filter=event.target.value;filterTasks();}if(event.target.id==="knowledge-search")filterKnowledge(event.target.value);});
document.addEventListener("change",event=>{if(event.target.id==="status-filter"){state.status=event.target.value;filterTasks();}if(event.target.id==="archive-filter"){state.archived=event.target.checked;filterTasks();}});
$("#create-form").addEventListener("submit",async event=>{event.preventDefault();const form=event.target;$("#create-submit").disabled=true;try{const task=await api("/api/tasks",{request_id:form.dataset.request,title:form.elements.title.value,question:form.elements.question.value});$("#create-dialog").close();location.hash="task/"+task.id;if(state.route==="task/"+task.id)await route();}catch(error){$("#create-error").textContent=error.message;}finally{$("#create-submit").disabled=false;}});
$("#decision-form").addEventListener("submit",async event=>{event.preventDefault();$("#decision-submit").disabled=true;try{const {task,...payload}=state.decision;await api(`/api/tasks/${task}/actions`,{...payload,note:event.target.elements.note.value});$("#decision-dialog").close();await route(true);}catch(error){$("#decision-error").textContent=error.message;}finally{$("#decision-submit").disabled=false;}});
$("#revision-form").addEventListener("submit",async event=>{event.preventDefault();const form=event.target;$("#revision-submit").disabled=true;try{
  const limitations=form.elements.limitations.value.split("\n").map(v=>v.trim()).filter(Boolean);
  if(limitations.length<1||limitations.length>8)throw Error("请输入1—8条限制。");
  await api(`/api/tasks/${form.dataset.task}/revisions`,{request_id:form.dataset.request,expected_hash:form.dataset.hash,
    summary:form.elements.summary.value,limitations,note:form.elements.note.value,confirmed:form.elements.confirmed.checked});
  $("#revision-dialog").close();await route(true);
}catch(error){$("#revision-error").textContent=error.message;}finally{$("#revision-submit").disabled=false;}});
window.addEventListener("hashchange",()=>route());
setInterval(async()=>{if(document.hidden||document.querySelector("dialog[open]")||state.loading||!state.boot)return;const busy=state.route.startsWith("task/")?state.task?.busy:["tasks","dashboard"].includes(state.route)&&state.tasks.some(t=>t.busy);if(busy){state.loading=true;try{await route(true);}finally{state.loading=false;}}},1500);
async function authStart(){
  const response=await fetch('/api/auth/session',{cache:'no-store'}),session=await response.json();
  if(session.auth_required && !session.authenticated){
    state.loginCsrf=session.login_csrf;document.body.classList.add('auth-locked');$('#auth-screen').hidden=false;
    $('#login-form').elements.username.focus();return;
  }
  document.body.classList.remove('auth-locked');$('#auth-screen').hidden=true;
  state.boot=await api('/api/bootstrap');
  $('#logout-button').hidden=!secure();
  if(secure()){
    document.body.dataset.role=role();
    $('.workspace-owner').innerHTML=`<span class="avatar" aria-hidden="true">${escape(state.boot.identity.username.slice(0,1).toUpperCase())}</span><span>${escape(state.boot.identity.username)}<small>${escape(({researcher:'研究者',reviewer:'审核者',admin:'管理员'})[role()])}</small></span>`;
    $('.mode-label').textContent='身份隔离 · 离线';
    $('#security-nav').hidden=role()!=='admin';
  }
  await route();
}
$('#login-form').addEventListener('submit',async event=>{
  event.preventDefault();const form=event.target,submit=form.querySelector('button');submit.disabled=true;
  try{
    const response=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.loginCsrf},
      body:JSON.stringify({username:form.elements.username.value,password:form.elements.password.value})});
    const data=await response.json();if(!response.ok)throw Error(`${data.error.message} (${data.error.code})`);
    form.elements.password.value='';$('#login-error').textContent='';await authStart();
  }catch(error){$('#login-error').textContent=error.message;}finally{submit.disabled=false;}
});
$('#logout-button').addEventListener('click',async()=>{
  try{await api('/api/auth/logout',{});state.boot=null;state.task=null;location.hash='dashboard';await authStart();}
  catch(error){toast(error.message);}
});
(async()=>{try{await authStart();}catch(error){$('#content').innerHTML=notice(error.message,'error');}})();

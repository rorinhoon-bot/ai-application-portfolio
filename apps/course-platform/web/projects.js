/* Frozen scope and explicit candidate-to-version execution contract. */
let projectRequest = 0;
let activeProject = null;
async function projectsPage() {
  const request = ++projectRequest;
  const data = await api('/api/projects');
  if(state.route !== 'projects' || request !== projectRequest)return;
  $('#content').innerHTML = heading('研究项目','先确定问题与资料范围，再整理可复核的依据。',
    (researcher()?'<button class="button primary" data-project-create>创建研究项目</button>':''))+
    '<div class="notice">研究项目先冻结问题和资料，再为2—4个候选创建待审批任务。执行使用本机离线脚本模型。</div>'+
    (data.projects.length ? `<section class="panel">${data.projects.map(p=>`<article class="project-summary"><div><h2><a href="#project/${escape(p.project_id)}">${escape(p.title)}</a></h2><p>${escape(p.question)}</p><span class="muted">${p.version_ids.length} 份冻结资料 · ${escape(time(p.created_at))}</span></div><a class="button secondary" href="#project/${escape(p.project_id)}">查看范围</a></article>`).join('')}</section>` :
    '<section class="panel empty"><h2>从一个明确的问题开始</h2><p>先导入项目资料，再选择本次研究所用版本。</p><a class="button secondary" href="#library">整理项目资料</a></section>');
}
async function openProjectCreate() {
  const routeAtOpen = state.route, data = await api('/api/library');
  if(state.route !== routeAtOpen)return;
  const form = $('#project-create-form');form.reset();form.dataset.request = uuid();
  $('#reviewer-choice').hidden=!secure();
  if(secure()){
    form.elements.reviewer_id.innerHTML=(state.boot.reviewers||[]).map(u=>`<option value="${escape(u.user_id)}">${escape(u.username)}</option>`).join('');
    form.elements.reviewer_id.required=true;
  }
  $('#project-create-error').textContent = '';
  $('#project-version-options').innerHTML = data.documents.length ? data.documents.map(d=>
    `<label class="project-source-choice"><input type="checkbox" name="versions" value="${escape(d.version_id)}"><span><strong>${escape(d.title)}</strong><small>${escape(d.source_ref)}<br>当前版本 ${escape(d.version_id.slice(4,16))} · ${d.chunk_count} 段</small></span></label>`).join('') :
    '<p>还没有项目资料。请先关闭表单，进入“项目资料”导入文本。</p>';
  $('#project-create-submit').disabled = !data.documents.length || (secure() && !state.boot.reviewers.length);
  $('#project-create-dialog').showModal();
}
async function projectPage(id) {
  const request = ++projectRequest, [p,tasks] = await Promise.all([api('/api/projects/'+id),api('/api/tasks')]);
  if(state.route !== 'project/'+id || request !== projectRequest)return;
  activeProject = p;
  const linked=tasks.tasks.filter(t=>t.execution?.project_id===id);
  $('#content').innerHTML = heading(p.title,'范围已保存，资料更新不会替换这里的版本。',
    '<a class="button secondary" href="#projects">所有研究项目</a>'+(researcher()?'<button class="button primary" data-project-run '+(p.manifest.length<2?'disabled':'')+'>创建研究任务</button>':''))+
    '<div class="notice">任务需2—4份不同冻结资料。范围审批通过后运行P1分词、P2脚本研究和P3只读MCP；结果仍需人工核查内容。</div>'+
    `<div class="project-scope-grid"><section class="panel panel-body"><h2>研究问题</h2><p class="project-prose">${escape(p.question)}</p><h3>项目约束</h3>${p.constraints.length?`<ul>${p.constraints.map(c=>`<li>${escape(c)}</li>`).join('')}</ul>`:'<p class="muted">未填写附加约束</p>'}<details class="source-details"><summary>范围指纹与记录</summary><code class="hash">${escape(p.contract_hash)}</code><p>${escape(p.project_id)}</p><p>${escape(time(p.created_at))} · 本机操作者确认保存</p><p>${p.events.length} 条创建记录 · 未启动引擎</p></details></section>
    <section class="panel panel-body"><h2>冻结资料 · ${p.manifest.length} 份</h2>${p.manifest.map(m=>`<details class="project-source"><summary>${escape(m.title)}</summary><p>来源：${escape(m.source_ref)}</p><p>授权：${escape(m.rights_note)}</p><p>版本</p><code class="hash">${escape(m.version_id)}</code><p>原文 SHA-256</p><code class="hash">${escape(m.content_hash)}</code></details>`).join('')}</section></div>
    <section class="panel panel-body"><h2>关联任务 · ${linked.length}</h2>${linked.length?linked.map(t=>`<p><a href="#task/${escape(t.id)}">${escape(t.title)}</a> · ${escape(t.status)} · ${escape(time(t.created_at))}</p>`).join(''):'<p class="muted">尚无关联任务。至少冻结两份资料才能执行。</p>'}</section>
    <section class="panel panel-body"><h2>检索本次研究资料</h2><form id="project-scope-search" class="project-query-form"><label class="sr-only" for="scope-query">冻结资料查询词</label><input id="scope-query" type="search" maxlength="200" placeholder="输入需要查找的关键词"><button class="button primary">检索冻结资料</button></form><div id="scope-results" aria-live="polite"></div></section>`;
  $('#project-scope-search').addEventListener('submit',async event=>{
    event.preventDefault();const sequence = ++projectRequest, target = state.route;
    $('#scope-results').textContent = '正在检索冻结资料…';
    try {
      const result = await api(`/api/projects/${id}/search`,{query:$('#scope-query').value,top_k:10});
      if(state.route!==target || sequence!==projectRequest)return;
      $('#scope-results').innerHTML = `<p class="muted">命中 ${result.results.length} 段，检索范围共 ${result.searched_chunks} 段。排序分不是可信度。</p>`+
        (result.results.length?result.results.map(r=>`<article class="project-evidence"><h3>${escape(r.title)}</h3><p>${escape(r.locator)} · 排序分 ${r.score}</p><pre>${escape(r.text)}</pre><button class="button secondary" data-project-evidence data-project="${escape(id)}" data-version="${escape(r.version_id)}" data-chunk="${escape(r.chunk_id)}" data-hash="${escape(r.content_hash)}">核验原文</button><p class="muted" role="status"></p></article>`).join(''):
        '<p>没有匹配依据。请更换关键词；需要新资料时创建新的研究范围。</p>');
    }catch(error){if(state.route===target && sequence===projectRequest)$('#scope-results').innerHTML=notice(error.message,'error');}
  });
}
document.addEventListener('click',async event=>{
  const create = event.target.closest('[data-project-create]');
  const run = event.target.closest('[data-project-run]');
  const verify = event.target.closest('[data-project-evidence]');
  try {
    if(create)await openProjectCreate();
    if(run && activeProject){
      const form=$('#project-run-form');form.reset();form.dataset.request=uuid();form.dataset.project=activeProject.project_id;
      form.dataset.contract=activeProject.contract_hash;$('#project-run-error').textContent='';
      $('#project-run-options').innerHTML=activeProject.manifest.map(m=>`<label class="project-source-choice"><input type="checkbox" name="selected" value="${escape(m.version_id)}"><span><strong>${escape(m.title)}</strong><small>${escape(m.version_id.slice(0,20))} · ${escape(m.rights_note)}</small><input class="candidate-name" aria-label="${escape(m.title)}的候选名称" maxlength="100" value="${escape(m.title)}"></span></label>`).join('');
      $('#project-run-dialog').showModal();
    }
    if(verify){
      verify.disabled=true;
      const result = await api(`/api/projects/${verify.dataset.project}/evidence`,{
        version_id:verify.dataset.version,chunk_id:verify.dataset.chunk,content_hash:verify.dataset.hash});
      if(result.binding_verified && verify.isConnected)verify.nextElementSibling.textContent='核验通过：原文属于冻结范围，内容指纹一致。';
    }
  }catch(error){toast(error.message);}finally{if(verify)verify.disabled=false;}
});
document.addEventListener('DOMContentLoaded',()=>{
  $('#project-run-form').addEventListener('submit',async event=>{
    event.preventDefault();const form=event.target,button=$('#project-run-submit');button.disabled=true;
    try {
      const candidates=[...form.querySelectorAll('input[name="selected"]:checked')].map(input=>({name:input.closest('label').querySelector('.candidate-name').value.trim(),version_id:input.value}));
      if(candidates.length<2||candidates.length>4)throw Error('请选择2—4个不同候选。');
      const task=await api(`/api/projects/${form.dataset.project}/tasks`,{request_id:form.dataset.request,
        expected_contract_hash:form.dataset.contract,candidates,confirmed:form.elements.confirmed.checked});
      $('#project-run-dialog').close();location.hash='task/'+task.id;
    }catch(error){$('#project-run-error').textContent=error.message;}finally{button.disabled=false;}
  });
  $('#project-create-form').addEventListener('submit',async event=>{
    event.preventDefault();const form=event.target,button=$('#project-create-submit');button.disabled=true;
    try {
      const version_ids=Array.from(form.querySelectorAll('input[name="versions"]:checked'),e=>e.value);
      if(!version_ids.length)throw Error('请至少选择一份资料。');
      const p=await api('/api/projects',{request_id:form.dataset.request,title:form.elements.title.value,
        question:form.elements.question.value,constraints:form.elements.constraints.value.split('\n').map(s=>s.trim()).filter(Boolean),
        version_ids,confirmed:form.elements.confirmed.checked,...(secure()?{reviewer_id:form.elements.reviewer_id.value}:{})});
      $('#project-create-dialog').close();location.hash='project/'+p.project_id;
    }catch(error){$('#project-create-error').textContent=error.message;}finally{button.disabled=false;}
  });
});

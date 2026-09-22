/* Local project sources; independent of the fixed scripted research workflow. */
const libraryState={catalog:null, selected:null, searchSerial:0, revision:0};
async function libraryPage(){
  const data=await api('/api/library'); if(state.route!=='library')return;
  libraryState.catalog=data; libraryState.revision++; libraryState.searchSerial++;
  const documents=data.documents;
  $('#content').innerHTML=heading('项目资料','为技术选型整理可追溯的原文与版本。',researcher()?`<button class="button primary" data-lib-action="import">${icon('plus')} 导入资料</button>`:'')+
    `<div class="notice">资料保存在本机。TXT / Markdown 可检索并冻结到研究项目；固定离线示例仍使用自己的原资料。</div>`+
    `<section class="panel library-workspace"><div class="library-toolbar"><form id="library-search-form" class="library-search-form"><label class="sr-only" for="project-query">检索项目资料</label><input id="project-query" type="search" maxlength="200" placeholder="例如：断点恢复、approval、SQLite…"><label class="sr-only" for="project-source">查询范围</label><select id="project-source"><option value="">全部最新资料</option>${documents.map(d=>`<option value="${escape(d.document_id)}">${escape(d.title)}</option>`).join('')}</select><button class="button secondary">检索</button></form></div>`+
    `<div class="project-library-grid"><aside class="document-list"><div class="list-caption">资料 <span>${documents.length}/50</span></div>${documents.length?documents.map(d=>`<button class="document-item" data-lib-version="${escape(d.version_id)}"><span class="document-icon">${icon('file')}</span><span class="document-info"><strong>${escape(d.title)}</strong><span>${d.versions.length} 个版本 · ${d.chunk_count} 段</span><small>${escape(d.source_ref)}</small></span></button>`).join(''):'<div class="library-empty">还没有项目资料。<br>导入自己编写或有权使用的文本后即可检索。</div>'}</aside><article id="project-reader" class="project-reader" aria-label="项目原文阅读区"><div class="empty"><h2>保留原文，让依据可查</h2><p>从左侧选择资料，或导入第一份文本。<br>每次修订保留旧版本，搜索仅使用最新版本。</p></div></article></div></section>`+
    `<section id="project-search-results" aria-live="polite"></section><details class="panel library-audit"><summary>资料操作记录 · 最近 ${data.events.length} 条</summary>${data.events.length?data.events.map(e=>`<p><strong>导入新版本</strong> · ${escape(time(e.created_at))}<br><code class="hash">${escape(e.version_id)}</code><br>${e.details.chunk_count} 段 · ${e.details.bytes} 字节 · 本机操作者已确认使用授权</p>`).join(''):'<p>暂无导入记录。</p>'}</details>`;
  $('#library-search-form').addEventListener('submit',searchLibrary);
  if(documents.length)await readLibraryVersion(documents[0].version_id);
}
async function readLibraryVersion(version,chunkId=''){
  const serial=++libraryState.revision;
  const data=await api('/api/library/versions/'+version);
  if(state.route!=='library'||serial!==libraryState.revision)return;
  libraryState.selected=data;
  const documentInfo=libraryState.catalog.documents.find(d=>d.document_id===data.document_id);
  const latest=documentInfo.version_id===data.version_id;
  $('#project-reader').innerHTML=`<div class="reader-toolbar"><span>${icon('file')} ${escape(data.filename)}</span><span class="subtle-badge">${latest?'最新版本':'历史只读版本'}</span></div><div class="reader-content"><div class="project-reader-heading"><h2>${escape(data.title)}</h2>${researcher()?'<button class="button secondary" data-lib-action="revise">新增版本</button>':''}</div><p class="muted">来源：${escape(data.source_ref)}</p><label class="version-select">查看版本<select id="library-version">${documentInfo.versions.map((v,i)=>`<option value="${escape(v.version_id)}" ${v.version_id===version?'selected':''}>${i===0?'最新 · ':''}${escape(time(v.created_at))} · ${v.version_id.slice(4,12)}</option>`).join('')}</select></label><details class="source-details"><summary>授权说明与内容指纹</summary><p>${escape(data.rights_note)}</p><p>内容 SHA-256</p><code class="hash">${escape(data.content_hash)}</code><p>版本编号</p><code class="hash">${escape(data.version_id)}</code></details>${data.chunks.map(c=>`<section class="source-chunk ${c.chunk_id===chunkId?'selected-chunk':''}" id="${escape(c.chunk_id)}"><div class="evidence-meta">${escape(c.locator)}</div><pre>${escape(c.text)}</pre></section>`).join('')}</div>`;
  document.querySelectorAll('[data-lib-version]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.libVersion===documentInfo.version_id));
  $('#library-version').addEventListener('change',e=>readLibraryVersion(e.target.value).catch(error=>toast(error.message)));
  if(chunkId)document.getElementById(chunkId)?.scrollIntoView({block:'center'});
}
async function searchLibrary(event){
  event.preventDefault(); const serial=++libraryState.searchSerial;
  const query=$('#project-query').value.trim(), source=$('#project-source').value;
  $('#project-search-results').innerHTML='<p class="muted">正在检索本机资料…</p>';
  try{
    const result=await api('/api/library/search',{query,document_ids:source?[source]:[],top_k:10});
    if(state.route!=='library'||serial!==libraryState.searchSerial)return;
    $('#project-search-results').innerHTML=`<div class="page-heading"><div><h2>检索结果 · ${result.results.length} 段</h2><p>搜索了 ${result.searched_chunks} 段最新原文。排序分不代表可信度；本页不生成结论。</p></div></div>`+(result.results.length?result.results.map(r=>`<article class="panel search-result"><div><h3>${escape(r.title)}</h3><span class="muted">${escape(r.locator)} · 排序分 ${r.score}</span></div><pre>${escape(r.text)}</pre><p class="muted">来源：${escape(r.source_ref)}</p><button class="button secondary" data-lib-version="${escape(r.version_id)}" data-lib-chunk="${escape(r.chunk_id)}">定位原文</button></article>`).join(''):`<div class="panel empty"><h3>${query?'没有找到匹配依据':'请输入查询词'}</h3><p>可换一个关键词或查询范围；系统不会补写不存在的证据。</p></div>`);
  }catch(error){if(state.route==='library')$('#project-search-results').innerHTML=notice(error.message,'error');}
}
async function openLibraryImport(revise=false){
  const form=$('#library-import-form');form.reset();form.dataset.request=uuid();form.dataset.expected='';
  form.elements.filename.value='notes.md';form.elements.source_ref.readOnly=false;
  $('#library-import-error').textContent='';$('#library-file-status').textContent='选择文本文件，或直接粘贴正文。';
  $('#library-import-title').textContent=revise?'新增资料版本':'导入项目资料';
  if(revise){
    const selected=libraryState.selected, entry=libraryState.catalog.documents.find(d=>d.document_id===selected.document_id);
    const latest=await api('/api/library/versions/'+entry.version_id);
    for(const key of ['title','filename','source_ref','rights_note','content'])form.elements[key].value=latest[key];
    form.dataset.expected=latest.version_id;form.elements.source_ref.readOnly=true;
  }
  $('#library-import-dialog').showModal();
}
document.addEventListener('click',async event=>{
  const version=event.target.closest('[data-lib-version]');
  const action=event.target.closest('[data-lib-action]');
  try{if(version)await readLibraryVersion(version.dataset.libVersion,version.dataset.libChunk);if(action)await openLibraryImport(action.dataset.libAction==='revise');}catch(error){toast(error.message);}
});
document.addEventListener('DOMContentLoaded',()=>{
  $('#library-file').addEventListener('change',async event=>{
    const file=event.target.files[0];if(!file)return;
    try{
      if(!/\.(txt|md)$/i.test(file.name)||file.name.startsWith('.')||file.size>48000)throw Error('请选择不超过48000字节的 UTF-8 TXT/Markdown 普通文件。');
      const content=new TextDecoder('utf-8',{fatal:true}).decode(await file.arrayBuffer());
      const form=$('#library-import-form');form.elements.content.value=content;form.elements.filename.value=file.name;
      if(!form.elements.title.value)form.elements.title.value=file.name.replace(/\.[^.]+$/,'');
      $('#library-file-status').textContent=`已读取 ${file.name}，${file.size} 字节；确认导入后才保存。`;
      $('#library-import-error').textContent='';
    }catch(error){event.target.value='';$('#library-import-error').textContent='文件读取失败：请使用48000字节以内的 UTF-8 TXT/Markdown。';}
  });
  $('#library-import-form').addEventListener('submit',async event=>{
    event.preventDefault();const form=event.target,button=$('#library-import-submit');button.disabled=true;
    try{
      const payload={request_id:form.dataset.request,expected_version:form.dataset.expected,confirmed:form.elements.confirmed.checked};
      for(const key of ['title','filename','source_ref','rights_note','content'])payload[key]=form.elements[key].value;
      const data=await api('/api/library/import',payload);
      $('#library-import-dialog').close();toast('资料已保存，来源与版本记录已保留');
      await libraryPage();if(state.route==='library')await readLibraryVersion(data.version_id);
    }catch(error){$('#library-import-error').textContent=error.message;}finally{button.disabled=false;}
  });
});

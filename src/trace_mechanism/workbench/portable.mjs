export async function post(path, value) {
  const res = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'},body:JSON.stringify(value)});
  const out = await res.json();
  if (!res.ok) throw Error(out.error || 'Local request failed');
  return out;
}
export function host(action,...args) {
  if (!window.pywebview?.api) return null;
  return window.pywebview.api[action](window.__agentTraceKey,...args);
}
export async function deliver(text,action) {
  if (action==='save') {
    const native=host('save',text);
    if(native) return await native;
    const url=URL.createObjectURL(new Blob([text],{type:'text/plain'}));
    const a=document.createElement('a');a.href=url;a.download='agent-trace.txt';a.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);return 'Downloaded';
  }
  const native=host('copy',text);
  if(native) return await native;
  await navigator.clipboard.writeText(text);
  return 'Copied';
}
export function editPrompts(reload) {
  const el=id=>document.getElementById(id);
  let revision=null;
  async function pick(slug) {
    const data=slug?await (await fetch('/prompt-shelf/'+encodeURIComponent(slug))).json():{};
    el('prompt-name').value=slug; el('prompt-name').disabled=!!slug;
    el('prompt-md').value=data.raw||''; revision=data.revision||null;
    el('edit-note').textContent='';
  }
  el('manage-prompts').onclick=async()=>{
    try {
      const data=await (await fetch('/prompt-shelf')).json();
      el('prompt-choose').replaceChildren(new Option('New prompt',''),...data.items.map(i=>new Option(i.title,i.slug)));
      el('prompt-dir').textContent=data.directory;
      await pick('');el('prompt-dialog').showModal();
    } catch(e) {el('prompts-receipt').textContent=e.message;}
  };
  el('prompt-choose').onchange=()=>pick(el('prompt-choose').value).catch(e=>el('edit-note').textContent=e.message);
  el('prompt-save').onclick=async()=>{
    try {
      await post('/save-prompt',{slug:el('prompt-name').value.trim(),raw:el('prompt-md').value,revision});
      el('prompt-dialog').close();await reload();
    } catch(e){el('edit-note').textContent=e.message;}
  };
  el('prompt-cancel').onclick=()=>el('prompt-dialog').close();
}

export async function post(path, value) {
  const res = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'},body:JSON.stringify(value)});
  const out = await res.json();
  if (!res.ok) throw Error(out.error || 'Local request failed');
  return out;
}
export const desktop=Boolean(document.querySelector('meta[name=agent-trace-desktop]'));
export function host(action,value) {
  if (!desktop) return null;
  return post('/window',{action,value}).then(response=>response.value);
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
  const editor = el('prompt-dialog');
  const confirm = el('editor-confirm');
  let original = {}, slug = '', loading = 0, pending = null;
  function question(message, action, accept) {
    pending = accept;
    el('editor-question').textContent = message;
    el('editor-accept').textContent = action;
    confirm.showModal();
    el('editor-keep').focus();
  }
  el('editor-keep').onclick = () => { pending = null; confirm.close(); };
  el('editor-accept').onclick = () => { const accept = pending; pending = null; confirm.close(); accept?.(); };
  function leave(action) {
    if (el('prompt-md').value !== (original.raw || '') || el('prompt-name').value !== slug)
      question('Discard your unsaved prompt changes?', 'Discard changes', action);
    else action();
  }
  async function pick(next) {
    const generation = ++loading;
    try {
      const response = next ? await fetch('/prompt-shelf/'+encodeURIComponent(next)) : null;
      const data = response ? await response.json() : {};
      if (generation !== loading) return;
      if (response && !response.ok) throw Error(data.error || 'Prompt could not be opened.');
      original = data; slug = next;
      el('prompt-choose').value = next;
      el('prompt-name').value = next; el('prompt-name').disabled = Boolean(next);
      el('prompt-md').value = data.raw || ''; el('prompt-output').hidden = true;
      el('prompt-remove').hidden = !data.user;
      el('prompt-remove').textContent = data.starter ? 'Restore starter' : 'Delete prompt';
      el('edit-note').textContent = data.raw && !data.user ? 'Saving creates a personal copy of this starter.' : '';
    } catch (error) { el('edit-note').textContent = error.message; }
  }
  async function refreshChoices() {
    const response = await fetch('/prompt-shelf');
    const data = await response.json();
    if (!response.ok) throw Error(data.error);
    el('prompt-choose').replaceChildren(new Option('New prompt',''),...data.items.map(i=>new Option(i.title,i.slug)));
    el('prompt-dir').textContent = data.directory;
  }
  el('manage-prompts').onclick = async () => {
    try { await refreshChoices(); await pick(''); editor.showModal(); }
    catch(error) { el('prompts-receipt').textContent = error.message; }
  };
  el('prompt-choose').onchange = event => {
    const next = event.target.value; event.target.value = slug;
    leave(() => pick(next));
  };
  el('prompt-save').onclick = async () => {
    try {
      await post('/save-prompt',{slug:el('prompt-name').value.trim(),raw:el('prompt-md').value,revision:original.revision || null});
      editor.close(); await reload();
    } catch(error) { el('edit-note').textContent = error.message; }
  };
  el('prompt-remove').onclick = () => {
    const action = original.starter ? 'Restore starter' : 'Delete prompt';
    question(original.starter ? 'Remove your edits and restore the bundled starter?' : 'Delete this personal prompt?', action, async () => {
      try {
        const result = await post('/remove-prompt',{slug,revision:original.revision});
        await refreshChoices(); await pick(result.restored ? slug : ''); await reload();
      } catch(error) { el('edit-note').textContent = error.message; }
    });
  };
  el('prompt-md').oninput = () => {el('prompt-output').hidden=true;};
  el('prompt-preview').onclick = async () => {
    try {
      const raw = el('prompt-md').value;
      const {text} = await post('/preview-prompt',{raw});
      if (el('prompt-md').value === raw) {el('prompt-output').textContent=text; el('prompt-output').hidden=false;}
    } catch(error) {el('edit-note').textContent=error.message;}
  };
  el('prompt-cancel').onclick = () => leave(() => editor.close());
  editor.oncancel = event => { event.preventDefault(); el('prompt-cancel').click(); };
}

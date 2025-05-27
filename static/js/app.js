const q = id => document.getElementById(id);

const mapping = {
  specName: 'name',
  pageWidth: 'page_width_cm',
  pageHeight: 'page_height_cm',
  marginTop: 'top_margin_cm',
  marginBottom: 'bottom_margin_cm',
  marginLeft: 'left_margin_cm',
  marginRight: 'right_margin_cm',
  requiresToc: 'requires_toc',
  noColorPages: 'no_color_pages',
  noImages: 'no_images',
};

function createTableRow(spec) {
  const tr = document.createElement('tr');
  tr.innerHTML = `
    <td>${spec.name}</td>
    <td class="text-end">
      <button data-action="edit" data-id="${spec.id}" class="btn btn-sm btn-primary me-2">Modifica</button>
      <button data-action="delete" data-id="${spec.id}" class="btn btn-sm btn-danger">Elimina</button>
    </td>
  `;
  return tr;
}

function createOption(spec) {
  const opt = document.createElement('option');
  opt.value = spec.id;
  opt.textContent = spec.name;
  return opt;
}

function setSpecFormValues(spec) {
  for (const [id, prop] of Object.entries(mapping)) {
    const el = q(id);
    if (!el) continue;
    if (el.type === 'checkbox') {
      el.checked = spec[prop];
    } else {
      el.value = spec[prop];
    }
  }
}

function getSpecFormData() {
  const data = {};
  for (const [id, prop] of Object.entries(mapping)) {
    const el = q(id);
    if (!el) continue;

    if (el.type === 'checkbox') {
      data[prop] = el.checked;
    } else if (id === 'specName') {           // ← lascialo stringa
      data[prop] = el.value.trim();
    } else {
      const val = parseFloat(el.value);
      data[prop] = isNaN(val) ? 0 : val;
    }
  }
  return data;
}

async function safeFetch(url, options = {}) {
  try {
    const res = await fetch(url, options);
    if (!res.ok) throw new Error(await res.text());
    return res;
  } catch (err) {
    alert(err.message);
    throw err;
  }
}

async function fetchSpecs() {
  const tbody = q('specTable');
  tbody.textContent = '';
  q('specSelect').innerHTML = '';
  try {
    const res = await safeFetch('/api/specs');
    const specs = await res.json();
    q('noSpecs').style.display = specs.length ? 'none' : 'block';
    specs.forEach(spec => {
      tbody.appendChild(createTableRow(spec));
      q('specSelect').appendChild(createOption(spec));
    });
  } catch {
    q('noSpecs').style.display = 'block';
  }
}

function openModal(mode, spec = null) {
  q('specForm').reset();
  q('specMsg').textContent = '';
  q('specId').value = spec ? spec.id : '';
  q('specModalTitle').textContent = mode === 'new' ? 'Nuova Specifica' : 'Modifica Specifica';
  if (spec) setSpecFormValues(spec);
  const modal = bootstrap.Modal.getOrCreateInstance(q('specModal'));
  modal.show();
}

async function saveSpec(e) {
  e.preventDefault();
  const id = q('specId').value;
  const url = id ? `/api/specs/${id}` : '/api/specs';
  const method = id ? 'PUT' : 'POST';
  const body = getSpecFormData();
  try {
    const res = await safeFetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    q('specMsg').textContent = id ? 'Specifiche aggiornate con successo' : 'Specifiche create con successo';
    q('specMsg').className = 'text-success me-auto';
    bootstrap.Modal.getInstance(q('specModal')).hide();
    await fetchSpecs();
  } catch (err) {
    q('specMsg').textContent = err.message;
    q('specMsg').className = 'text-danger me-auto';
  }
}

async function deleteSpec(id) {
  if (!confirm('Cancellare la specifica?')) return;
  try {
    await safeFetch(`/api/specs/${id}`, { method: 'DELETE' });
    await fetchSpecs();
  } catch {
    alert('Errore nella cancellazione');
  }
}

async function validaDocumento() {
  const id = q('specSelect').value;
  const fileInput = q('fileInput');
  if (!id) { alert('Seleziona una specifica'); return; }
  if (!fileInput.files.length) { alert('Seleziona un file'); return; }
  q('validateSpinner').style.display = 'block';
  q('resultCard').style.display = 'none';

  const fd = new FormData();
  fd.append('file', fileInput.files[0]);

  try {
    const res = await safeFetch(`/api/validate/${id}`, { method: 'POST', body: fd });
    const data = await res.json();
    q('resultJson').textContent = JSON.stringify(data, null, 2);
    q('downloadReportBtn').onclick = () => scaricaReport(data.id);
    q('resultCard').style.display = 'block';
  } catch (err) {
    alert(err.message);
  } finally {
    q('validateSpinner').style.display = 'none';
  }
}

async function scaricaReport(id) {
  try {
    const res = await safeFetch(`/api/validation-reports/${id}`, {
      method: 'POST',                               // prima era GET implicito
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        include_charts: true,
        include_detailed_analysis: true,
        include_recommendations: true,
      }),
    });
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `validation_report_${id}.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (err) {
    alert(err.message);
  }
}

document.addEventListener('DOMContentLoaded', async () => {
  await fetchSpecs();
  q('newSpecBtn').addEventListener('click', () => openModal('new'));
  q('specTable').addEventListener('click', async e => {
    const btn = e.target.closest('button[data-action]');
    if (!btn) return;
    const id = btn.dataset.id;
    if (btn.dataset.action === 'edit') {
      try {
        const res = await safeFetch(`/api/specs/${id}`);
        const spec = await res.json();
        openModal('edit', spec);
      } catch {}
    } else if (btn.dataset.action === 'delete') {
      await deleteSpec(id);
    }
  });
  q('specForm').addEventListener('submit', saveSpec);
  q('validateBtn').addEventListener('click', validaDocumento);
});
/******************** TEMPLATE E-MAIL *************************/
function tplRow(tpl) {
  const tr = document.createElement('tr');
  tr.innerHTML = `
    <td>${tpl.subject}</td>
    <td class="text-end">
      <button data-action="edit-tpl" data-id="${tpl.id}" class="btn btn-sm btn-primary me-2">Modifica</button>
      <button data-action="delete-tpl" data-id="${tpl.id}" class="btn btn-sm btn-danger">Elimina</button>
    </td>`;
  return tr;
}

async function fetchTpls() {
  const tbody = q('tplTable');
  tbody.textContent = '';
  try {
    const res = await safeFetch('/api/email-templates');
    const tpls = await res.json();
    q('noTpl').style.display = tpls.length ? 'none' : 'block';
    tpls.forEach(tpl => tbody.appendChild(tplRow(tpl)));
  } catch {
    q('noTpl').style.display = 'block';
  }
}

function openTplModal(mode, tpl = null) {
  q('tplForm').reset();
  q('tplMsg').textContent = '';
  q('tplId').value = tpl ? tpl.id : '';
  q('tplModalTitle').textContent = mode === 'new' ? 'Nuovo template' : 'Modifica template';
  if (tpl) {
    q('tplSubject').value = tpl.subject;
    q('tplBody').value = tpl.body;
  }
  const modal = bootstrap.Modal.getOrCreateInstance(q('tplModal'));
  modal.show();
}

async function saveTpl(e) {
  e.preventDefault();
  const id = q('tplId').value;
  const url = id ? `/api/email-templates/${id}` : '/api/email-templates';
  const method = id ? 'PUT' : 'POST';
  const body = {
    subject: q('tplSubject').value,
    body: q('tplBody').value
  };
  try {
    await safeFetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    bootstrap.Modal.getInstance(q('tplModal')).hide();
    await fetchTpls();
  } catch (err) {
    q('tplMsg').textContent = err.message;
    q('tplMsg').className = 'text-danger me-auto';
  }
}

async function deleteTpl(id) {
  if (!confirm('Cancellare il template?')) return;
  try {
    await safeFetch(`/api/email-templates/${id}`, { method: 'DELETE' });
    await fetchTpls();
  } catch {
    alert('Errore nella cancellazione');
  }
}

/* — hook nel DOMContentLoaded esistente — */
document.addEventListener('DOMContentLoaded', async () => {
  await fetchTpls();             // ⬅️ nuovo
  /* pulsanti esistenti… */
  q('newTplBtn').addEventListener('click', () => openTplModal('new'));
  q('tplTable').addEventListener('click', async e => {
    const btn = e.target.closest('button[data-action]');
    if (!btn) return;
    const id = btn.dataset.id;
    if (btn.dataset.action === 'edit-tpl') {
      const res = await safeFetch(`/api/email-templates/${id}`);
      const tpl = await res.json();
      openTplModal('edit', tpl);
    } else if (btn.dataset.action === 'delete-tpl') {
      await deleteTpl(id);
    }
  });
  q('tplForm').addEventListener('submit', saveTpl);
});
/**************************************************************/

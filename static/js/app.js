/* -------------------- utilities -------------------- */
const q = id => document.getElementById(id);

/* ------------ CRUD SPECIFICHE -------------- */
async function fetchSpecs() {
  const tbody = q('specTable');
  tbody.innerHTML = '';
  q('specSelect').innerHTML = '';

  const res = await fetch('/api/specs');
  const specs = res.ok ? await res.json() : [];

  q('noSpecs').style.display = specs.length ? 'none' : 'block';

  specs.forEach(s => {
    // tabella
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${s.name}</td>
      <td class="text-end">
        <button class="btn btn-sm btn-outline-secondary me-2"
                data-id="${s.id}" data-action="edit">Modifica</button>
        <button class="btn btn-sm btn-outline-danger"
                data-id="${s.id}" data-action="del">Elimina</button>
      </td>`;
    tbody.appendChild(tr);

    // select validazione
    const opt = document.createElement('option');
    opt.value = s.id;
    opt.textContent = s.name;
    q('specSelect').appendChild(opt);
  });
}

function openModal(mode, spec = null) {
  // reset campi
  q('specForm').reset();
  q('specMsg').textContent = '';
  q('specId').value = spec ? spec.id : '';

  q('specModalTitle').textContent =
    mode === 'new' ? 'Nuova specifica' : 'Modifica specifica';

  if (spec) {
    q('specName').value       = spec.name;
    q('pageWidth').value      = spec.page_width_cm;
    q('pageHeight').value     = spec.page_height_cm;
    q('marginTop').value      = spec.top_margin_cm;
    q('marginBottom').value   = spec.bottom_margin_cm;
    q('marginLeft').value     = spec.left_margin_cm;
    q('marginRight').value    = spec.right_margin_cm;
    q('requiresToc').checked  = spec.requires_toc;
    q('noColorPages').checked = spec.no_color_pages;
    q('noImages').checked     = spec.no_images;
  }

  // istanzia (o recupera) l’oggetto modale **dopo** che l'elemento esiste
  const modal = bootstrap.Modal.getOrCreateInstance(q('specModal'));
  modal.show();
}

async function saveSpec(e) {
  e.preventDefault();
  const id = q('specId').value;
  const body = {
    name           : q('specName').value,
    page_width_cm  : parseFloat(q('pageWidth').value),
    page_height_cm : parseFloat(q('pageHeight').value),
    top_margin_cm  : parseFloat(q('marginTop').value),
    bottom_margin_cm:parseFloat(q('marginBottom').value),
    left_margin_cm : parseFloat(q('marginLeft').value),
    right_margin_cm: parseFloat(q('marginRight').value),
    requires_toc   : q('requiresToc').checked,
    no_color_pages : q('noColorPages').checked,
    no_images      : q('noImages').checked
  };

  const method = id ? 'PUT' : 'POST';
  const url    = id ? `/api/specs/${id}` : '/api/specs';

  const res = await fetch(url, {
    method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
  });

  if (!res.ok) {
    q('specMsg').textContent = await res.text();
    q('specMsg').className   = 'text-danger me-auto';
    return;
  }

  bootstrap.Modal.getInstance(q('specModal')).hide();
  await fetchSpecs();
}

async function deleteSpec(id) {
  if (!confirm('Cancellare la specifica?')) return;
  const res = await fetch(`/api/specs/${id}`, { method: 'DELETE' });
  if (!res.ok) { alert('Errore nella cancellazione'); return; }
  await fetchSpecs();
}

/* ------------------ VALIDAZIONE ------------------ */
async function validaDocumento() {
  const id = q('specSelect').value;
  if (!id) { alert('Seleziona una specifica'); return; }
  if (!q('fileInput').files.length) { alert('Seleziona un file'); return; }

  q('validateSpinner').style.display = 'block';
  q('resultCard').style.display = 'none';

  const fd = new FormData();
  fd.append('file', q('fileInput').files[0]);

  try {
    const res = await fetch(`/api/validate/${id}`, { method: 'POST', body: fd });
    if (!res.ok) throw new Error(await res.text());
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
  const res = await fetch(`/api/validation-reports/${id}`, {
    method : 'POST',
    headers: { 'Content-Type': 'application/json' },
    body   : JSON.stringify({
      include_charts:true,
      include_detailed_analysis:true,
      include_recommendations:true
    })
  });
  if (!res.ok) { alert(await res.text()); return; }
  const blob = await res.blob();
  const url  = URL.createObjectURL(blob);
  Object.assign(document.createElement('a'), {
    href: url, download: `report_${id}.pdf`
  }).click();
  URL.revokeObjectURL(url);
}

/* ------------------ EVENT BINDINGS ------------------ */
document.addEventListener('DOMContentLoaded', async () => {
  await fetchSpecs();

  // “Nuova”
  q('newSpecBtn').addEventListener('click', () => openModal('new'));

  // click in tabella (delegato)
  q('specTable').addEventListener('click', async e => {
    const btn = e.target.closest('button[data-action]');
    if (!btn) return;

    const { id, action } = btn.dataset;
    if (action === 'edit') {
      const res  = await fetch(`/api/specs/${id}`);
      const spec = await res.json();
      openModal('edit', spec);
    } else if (action === 'del') {
      await deleteSpec(id);
    }
  });

  // submit modale
  q('specForm').addEventListener('submit', saveSpec);

  // validazione
  q('validateBtn').addEventListener('click', validaDocumento);
});

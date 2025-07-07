const q = id => document.getElementById(id);

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


async function validaDocumento() {
  const orderText = q('orderText').value.trim();
  const fileInput = q('fileInput');

  if (!orderText) { alert('Incolla il testo dell’ordine'); return; }
  if (!fileInput.files.length) { alert('Seleziona un file'); return; }

  // endpoint fisso
  const url = '/api/validate-order';
  const fd  = new FormData();
  fd.append('order_text', orderText);
  fd.append('file', fileInput.files[0]);

  // UI: spinner on, nasconde risultato
  q('validateSpinner').style.display = 'block';
  q('resultCard').style.display = 'none';

  try {
    const res  = await safeFetch(url, { method: 'POST', body: fd });
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

document.addEventListener('DOMContentLoaded', () => {
  q('validateBtn').addEventListener('click', validaDocumento);
});

/******************** TEMPLATE E-MAIL *************************/
/*function tplRow(tpl) {
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
*/
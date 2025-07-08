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

  if (!orderText)            { alert('Incolla il testo dell’ordine'); return; }
  if (!fileInput.files.length){ alert('Seleziona un file'); return; }

  /*────────── richiesta ──────────*/
  const url = '/api/validate-order';
  const fd  = new FormData();
  fd.append('order_text', orderText);
  fd.append('file', fileInput.files[0]);

  /*────────── UI reset ──────────*/
  q('validateSpinner').style.display = 'block';
  q('resultCard').style.display      = 'none';
  q('fileInfoCard').style.display    = 'none';

  try {
    const res  = await safeFetch(url, { method: 'POST', body: fd });
    const data = await res.json();

    /*────────── estrazione proprietà ──────────*/
    const props = data.raw_props || {};
    const sz    = props.page_size || {};
    const mg    = props.margins   || {};
    const da    = props.detailed_analysis || {};

    const f = n => (typeof n === 'number' ? n.toFixed(1) : '—');
    // restituisce ✓ verde se ok, ✗ rosso se KO, stringa vuota se la chiave non esiste
    const tick = ok =>
      ok === undefined
        ? ''
        : `<span style="color:${ok ? '#198754' : '#d32f2f'};font-weight:bold;">${ok ? '✓' : '✗'}</span> `;

    /* stampa colori / B&N */
    const stampaHTML = (da.has_color_pages || da.has_color_text)
      ? '<span style="color:red;font-weight:bold;">COLORI</span>'
      : '<span style="font-weight:bold;">B/N</span>';

    /* pagine/elementi a colori (se disponibile) */
    const pagineColori = (typeof da.colored_elements_count === 'number')
                         ? da.colored_elements_count
                         : '—';

    /* intestazioni / piè di pagina */
    const intestazioni = Array.isArray(props.headers)   ? props.headers.length   : 0;
    const piedipagina  = Array.isArray(props.footnotes) ? props.footnotes.length : 0;

    /*────────── FONT: nome + dimensioni + occorrenze ──────────*/
    let fontLines = '  —';
    if (da.fonts && Object.keys(da.fonts).length) {
    
      // 1. ordina i font per occorrenze totali (discendente)
      const fontEntries = Object.entries(da.fonts)
        .sort(([, a], [, b]) => b.count - a.count);
    
      const rows = fontEntries.map(([name, info]) => {
        // 2. ordina le singole dimensioni per occorrenze (disc.)
        const sizes = Object.entries(info.size_counts)
          .sort(([, ca], [, cb]) => cb - ca)                 // maggiori prima
          .map(([size, cnt]) => `${size} pt → ${cnt}`)
          .join(' | ');
        return `  - ${name}: ${sizes}`;
      });
    
      fontLines = rows.join('\n');
    }

    /*────────── compila riquadro ──────────*/
    const v = data.validations || {};

    const infoLines = [
      'Dimensioni pagina:    ' + tick(v.page_size) + f(sz.width_cm) + ' × ' + f(sz.height_cm) + ' cm',
      'Stampa:               ' + tick(v.no_color_pages) + stampaHTML,
      'Pagine totali:        ' + (props.page_count != null ? props.page_count : '—'),
      'Pagine a colori:      ' + tick(v.no_color_pages) + pagineColori,
      'Margini (cm):         ' + tick(v.margins) + 'T ' + f(mg.top_cm) +
                               ' · B ' + f(mg.bottom_cm) +
                               ' · L ' + f(mg.left_cm) +
                               ' · R ' + f(mg.right_cm),
      'Intestazioni:         ' + tick(v.has_header) + intestazioni,
      'Piè di pagina:        ' + tick(v.has_footnotes) + piedipagina,
      'TOC presente:         ' + tick(v.has_toc) + (props.has_toc ? 'Sì' : 'No'),
      '',
      'Font (nome e dimensioni):',
      'Nome file:            ' + (data.document_name || '—'),
      'Formato file:         ' + ((data.file_format || '').toUpperCase() || '—'),
      fontLines
    ].join('\n');

    q('fileInfoText').innerHTML  = infoLines;   // ← innerHTML per il markup COLORI / B/N
    q('fileInfoCard').style.display = 'block';

    /*────────── JSON risultato ──────────*/
    q('resultJson').textContent   = JSON.stringify(data, null, 2);
    q('downloadReportBtn').onclick = () => scaricaReport(data.id);
    q('resultCard').style.display = 'block';
    q('downloadReportBtn').dataset.valId = data.id;

    /* ---------- Default e-mail ---------- */
    const failed = Object.entries(data.validations)
    .filter(([, ok]) => !ok)
    .map(([check]) => '• ' + check.replaceAll('_', ' '))
    .join('\n');

    const bodyTxt = data.is_valid
    ? `Ciao,

    il documento “${data.document_name}” risulta conforme ai requisiti. In allegato trovi il report dettagliato.

    Cordiali saluti`
    : `Ciao,

    durante la verifica di “${data.document_name}” abbiamo riscontrato queste incongruenze:

    ${failed || '—'}

    Ti chiediamo di correggerle; in allegato trovi il report dettagliato.

    Grazie, resto a disposizione.`;

    q('clientEmail').value = '';        // reset destinatario
    q('emailBody').value   = bodyTxt;   // pre-compila testo
    q('emailMsg').textContent = '';
    q('emailCard').style.display = 'block';

    const summary = q('summaryMsg');
    if (data.is_valid) {
      summary.innerHTML = '<span style="color:#198754;">IL FILE È CONFORME</span>';
    } else {
      const reasons = Object.entries(data.validations)
        .filter(([, ok]) => !ok)
        .map(([chk]) => chk.replaceAll('_', ' '))
        .join(', ');
      summary.innerHTML =
        `<span style="color:#d32f2f;">IL FILE NON È CONFORME</span>` +
        (reasons ? `<br/><small>Motivi: ${reasons}</small>` : '');
    }

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
  q('sendEmailBtn').addEventListener('click', sendEmail);
});

async function sendEmail() {
  const to    = q('clientEmail').value.trim();
  const body  = q('emailBody').value.trim();
  const valId = q('downloadReportBtn').dataset.valId;   // vedrai sotto

  q('emailMsg').className = ''; q('emailMsg').textContent = '';

  if (!to)   { q('emailMsg').textContent = 'E-mail mancante';  q('emailMsg').className='text-danger'; return; }
  if (!body) { q('emailMsg').textContent = 'Messaggio vuoto'; q('emailMsg').className='text-danger'; return; }

  try {
    const res = await safeFetch('/api/zendesk-ticket', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ email: to, message: body, validation_id: valId })
    });
    const data = await res.json();
    q('emailMsg').textContent = `Ticket #${data.ticket_id} creato`;
    q('emailMsg').className = 'text-success';
  } catch (err) {
    q('emailMsg').textContent = err.message;
    q('emailMsg').className = 'text-danger';
  }
}


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
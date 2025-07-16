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
  const selectedFile = window.getSelectedFile ? window.getSelectedFile() : (q('fileInput').files[0] || null);

  if (!orderText)     { alert('Incolla il testo dell\'ordine'); return; }
  if (!selectedFile)  { alert('Seleziona un file'); return; }

  /*────────── richiesta ──────────*/
  const url = '/api/validate-order';
  const fd  = new FormData();
  fd.append('order_text', orderText);
  fd.append('file', selectedFile);

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
    /* posizione numero di pagina */
    const posArr = Array.isArray(props.page_num_positions) ? props.page_num_positions : [];
    let posSintesi = '—';
    if (posArr.length) {
      const cnt = posArr.reduce((m, p) => (m[p] = (m[p] || 0) + 1, m), {});
      posSintesi = Object.entries(cnt)
        .map(([k, v]) => `${k}: ${v}`)
        .join(' | ');
    }

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

    // Controlla inconsistenze di formato
    let formatWarnings = '';
    if (props.inconsistent_pages && props.inconsistent_pages.length > 0) {
      const pages = props.inconsistent_pages.map(p => `Pag. ${p.page}: ${p.size}`).join(', ');
      formatWarnings = `\n⚠️  PAGINE CON FORMATO DIVERSO: ${pages}`;
    }
    if (props.inconsistent_sections && props.inconsistent_sections.length > 0) {
      const sections = props.inconsistent_sections.map(s => `Sez. ${s.section}: ${s.size}`).join(', ');
      formatWarnings = `\n⚠️  SEZIONI CON FORMATO DIVERSO: ${sections}`;
    }

    const infoLines = [
      'Dimensioni pagina:    ' + tick(v.page_size) + f(sz.width_cm) + ' × ' + f(sz.height_cm) + ' cm',
      'Consistenza formato:  ' + tick(v.format_consistency) + (v.format_consistency ? 'Uniforme' : 'Variabile') + formatWarnings,
      'Stampa:               ' + tick(v.no_color_pages) + stampaHTML,
      'Pagine totali:        ' + (props.page_count != null ? props.page_count : '—'),
      'Pagine a colori:      ' + tick(v.no_color_pages) + pagineColori,
      'Margini (cm):         ' + tick(v.margins) + 'T ' + f(mg.top_cm) +
                               ' · B ' + f(mg.bottom_cm) +
                               ' · L ' + f(mg.left_cm) +
                               ' · R ' + f(mg.right_cm),
      'Intestazioni:         ' + tick(v.has_header) + intestazioni,
      'Piè di pagina:        ' + tick(v.has_footnotes) + piedipagina,
      'Numerazione pagine:   ' + tick(v.page_numbers_position) + posSintesi,
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

    il documento "${data.document_name}" risulta conforme ai requisiti. In allegato trovi il report dettagliato.

    Cordiali saluti`
    : `Ciao,

    durante la verifica di "${data.document_name}" abbiamo riscontrato queste incongruenze:

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
      method: 'POST',
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

// Prevent default drag behaviors globally
function preventDefaults(e) {
  e.preventDefault();
  e.stopPropagation();
}

function setupDropArea() {
  const dropArea = q('dropArea');
  const fileInput = q('fileInput');
  const dropText = q('dropText');
  const fileName = q('fileName');
  const clearFileBtn = q('clearFileBtn');
  
  // Variable to store the dropped file
  let droppedFile = null;

  // Prevent default behaviors for the entire window
  window.addEventListener('dragenter', preventDefaults, false);
  window.addEventListener('dragover', preventDefaults, false);
  window.addEventListener('dragleave', preventDefaults, false);
  window.addEventListener('drop', preventDefaults, false);

  // Specific handlers for drop area
  ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
    dropArea.addEventListener(eventName, preventDefaults, false);
  });

  // Highlight drop area when item is dragged over it
  ['dragenter', 'dragover'].forEach(eventName => {
    dropArea.addEventListener(eventName, highlight, false);
  });

  ['dragleave', 'drop'].forEach(eventName => {
    dropArea.addEventListener(eventName, unhighlight, false);
  });

  // Handle dropped files
  dropArea.addEventListener('drop', handleDrop, false);
  
  // Handle click to open file dialog
  dropArea.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    fileInput.click();
  });
  
  // Handle file selection via input
  fileInput.addEventListener('change', handleFileSelect);
  
  // Handle clear file button
  clearFileBtn.addEventListener('click', clearFile);

  function highlight(e) {
    dropArea.classList.add('drag-over');
  }

  function unhighlight(e) {
    dropArea.classList.remove('drag-over');
  }

  function handleDrop(e) {
    e.preventDefault();
    e.stopPropagation();
    
    const dt = e.dataTransfer;
    const files = dt.files;
    
    if (files.length > 0) {
      const file = files[0];
      // Check file type
      const acceptedTypes = ['.pdf', '.docx', '.odt', '.doc'];
      const fileExtension = '.' + file.name.split('.').pop().toLowerCase();
      
      if (acceptedTypes.includes(fileExtension)) {
        droppedFile = file;
        // Try to update the file input as well
        try {
          const dataTransfer = new DataTransfer();
          dataTransfer.items.add(file);
          fileInput.files = dataTransfer.files;
        } catch (e) {
          // Fallback if DataTransfer is not supported
          console.log('DataTransfer not supported, using droppedFile variable');
        }
        updateFileDisplay(file);
      } else {
        alert('Tipo di file non supportato. Scegli un file PDF, DOCX, ODT o DOC.');
      }
    }
  }
  
  function handleFileSelect(e) {
    if (e.target.files.length > 0) {
      droppedFile = null; // Reset dropped file when using file input
      updateFileDisplay(e.target.files[0]);
    }
  }
  
  function updateFileDisplay(file) {
    dropText.style.display = 'none';
    fileName.style.display = 'block';
    fileName.textContent = file.name;
    clearFileBtn.style.display = 'block';
  }
  
  function clearFile() {
    // Reset all file-related elements
    droppedFile = null;
    fileInput.value = '';
    
    // Reset display
    dropText.style.display = 'block';
    fileName.style.display = 'none';
    fileName.textContent = '';
    clearFileBtn.style.display = 'none';
    
    // Reset any validation results
    q('fileInfoCard').style.display = 'none';
    q('emailCard').style.display = 'none';
    q('resultCard').style.display = 'none';
  }
  
  // Make the getSelectedFile function available globally
  window.getSelectedFile = function() {
    return droppedFile || (fileInput.files.length > 0 ? fileInput.files[0] : null);
  };
}

async function sendEmail() {
  const to    = q('clientEmail').value.trim();
  const body  = q('emailBody').value.trim();
  const valId = q('downloadReportBtn').dataset.valId;

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

document.addEventListener('DOMContentLoaded', () => {
  q('validateBtn').addEventListener('click', validaDocumento);
  q('sendEmailBtn').addEventListener('click', sendEmail);
  
  // Setup drag and drop functionality
  setupDropArea();
});

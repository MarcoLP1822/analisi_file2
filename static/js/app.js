/* ------------ funzioni utili -------------- */
async function caricaSpecifiche() {
    const sel = document.getElementById('specSelect');
    const alertBox = document.getElementById('specAlert'); // opzionale
  
    try {
      const res = await fetch('/api/specs');
      if (!res.ok) throw new Error(await res.text());
  
      const specs = await res.json();
      sel.innerHTML = '';
  
      if (specs.length === 0) {
        sel.disabled = true;
        if (alertBox) alertBox.style.display = 'block';
        return;
      }
  
      specs.forEach(s => {
        const opt = document.createElement('option');
        opt.value = s.id;
        opt.textContent = s.name;
        sel.appendChild(opt);
      });
  
      sel.disabled = false;
      if (alertBox) alertBox.style.display = 'none';
    } catch (err) {
      console.error(err);
      alert('Errore nel recupero delle specifiche');
    }
  }
  
  /* -------- submit del form di creazione -------- */
  document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('specForm');
    if (form) {
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
  
        const body = {
          name:           document.getElementById('specName').value,
          page_width_cm:  parseFloat(document.getElementById('pageWidth').value),
          page_height_cm: parseFloat(document.getElementById('pageHeight').value),
          top_margin_cm:  parseFloat(document.getElementById('marginTop').value),
          bottom_margin_cm: parseFloat(document.getElementById('marginBottom').value),
          left_margin_cm: parseFloat(document.getElementById('marginLeft').value),
          right_margin_cm:parseFloat(document.getElementById('marginRight').value),
          requires_toc:   document.getElementById('requiresToc').checked,
          no_color_pages: document.getElementById('noColorPages').checked,
          no_images:      document.getElementById('noImages').checked
        };
  
        const msgBox = document.getElementById('specMsg');
  
        try {
          const res = await fetch('/api/specs', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
          });
          if (!res.ok) throw new Error(await res.text());
  
          msgBox.innerHTML =
            '<div class="alert alert-success">Specifica salvata!</div>';
  
          form.reset();         // commenta se vuoi conservare i valori
          await caricaSpecifiche();
        } catch (err) {
          msgBox.innerHTML =
            `<div class="alert alert-danger">Errore: ${err}</div>`;
        }
      });
    }
  
    // carica subito la lista all'apertura della pagina
    caricaSpecifiche();
  });
  
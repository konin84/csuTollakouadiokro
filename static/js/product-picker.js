// Liste déroulante des produits avec recherche (nom ou code) : la flèche ou un clic ouvre toute la liste,
// la saisie la filtre.
// La liste <select class="product-select"> reste dans la page (cachée) : c'est elle qui est envoyée,
// et le reste du formulaire (prix, unités, stock) continue de lire sa valeur.
(function () {

  // accents retires : normalize('NFD') separe les signes diacritiques (U+0300 a U+036F), que l'on supprime
  var DIACRITICS = new RegExp('[' + String.fromCharCode(0x300) + '-' + String.fromCharCode(0x36f) + ']', 'g');

  function norm(s) {
    return (s || '').normalize('NFD').replace(DIACRITICS, '').toLowerCase().replace(/\s+/g, ' ').trim();
  }

  function enhance(select) {
    if (select.dataset.picker) return;
    select.dataset.picker = '1';
    select.hidden = true;

    var wrap = document.createElement('div');
    wrap.className = 'picker';
    var input = document.createElement('input');
    input.type = 'search';
    input.className = 'picker-input';
    input.placeholder = '— Choisir ou rechercher un produit —';
    input.autocomplete = 'off';
    input.setAttribute('role', 'combobox');
    input.setAttribute('aria-expanded', 'false');
    input.setAttribute('aria-autocomplete', 'list');
    var toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'picker-toggle';
    toggle.tabIndex = -1;
    toggle.setAttribute('aria-label', 'Afficher tous les produits');
    toggle.innerHTML = '<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M2.5 4.5 6 8l3.5-3.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    var list = document.createElement('ul');
    list.className = 'picker-list';
    list.setAttribute('role', 'listbox');
    list.hidden = true;
    wrap.append(input, toggle, list);
    select.parentNode.insertBefore(wrap, select);

    var items = Array.prototype.slice.call(select.options).filter(function (o) { return o.value; })
      .map(function (o) { return {opt: o, name: norm(o.text), key: norm(o.text + ' ' + (o.dataset.code || ''))}; })
      .sort(function (a, b) { return a.name.localeCompare(b.name, 'fr'); });   // ordre alphabétique (sans casse ni accents)
    var shown = [], active = -1;

    function current() { return select.options[select.selectedIndex]; }
    function showSelected() { var o = current(); input.value = o && o.value ? o.text : ''; }

    function close() { list.hidden = true; input.setAttribute('aria-expanded', 'false'); active = -1; }

    // liste « flottante » (position: fixed) sous le champ : jamais coupée par un tableau qui défile
    function place() {
      var r = input.getBoundingClientRect(), below = window.innerHeight - r.bottom - 8;
      list.style.left = r.left + 'px';
      list.style.width = Math.max(r.width, 260) + 'px';
      if (below < 180 && r.top > below) {        // peu de place en dessous : ouvrir au-dessus
        list.style.top = '';
        list.style.bottom = (window.innerHeight - r.top + 4) + 'px';
        list.style.maxHeight = Math.min(320, r.top - 12) + 'px';
      } else {
        list.style.bottom = '';
        list.style.top = (r.bottom + 4) + 'px';
        list.style.maxHeight = Math.min(320, below) + 'px';
      }
    }
    window.addEventListener('scroll', function () { if (!list.hidden) place(); }, true);
    window.addEventListener('resize', function () { if (!list.hidden) place(); });

    // all : liste complète (flèche, ou champ montrant le produit déjà choisi) ; sinon filtrée par la saisie
    function render(all) {
      var words = all ? [] : norm(input.value).split(' ').filter(Boolean);
      shown = items.filter(function (it) { return words.every(function (w) { return it.key.indexOf(w) !== -1; }); });
      list.innerHTML = '';
      if (!shown.length) {
        var none = document.createElement('li');
        none.className = 'picker-empty';
        none.textContent = 'Aucun produit trouvé';
        list.appendChild(none);
      }
      shown.forEach(function (it, i) {
        var li = document.createElement('li');
        li.setAttribute('role', 'option');
        li.dataset.i = i;
        var name = document.createElement('span');
        name.textContent = it.opt.text;
        var meta = document.createElement('span');
        meta.className = 'picker-meta';
        var stock = parseInt(it.opt.dataset.stock || '0', 10);
        meta.textContent = (it.opt.dataset.code ? it.opt.dataset.code + ' · ' : '') + 'stock ' + stock + ' ' + (it.opt.dataset.unit || '');
        if (stock <= 0) li.classList.add('picker-out');
        li.append(name, meta);
        list.appendChild(li);
      });
      var chosen = shown.findIndex(function (it) { return it.opt.value === select.value; });
      active = chosen >= 0 ? chosen : (shown.length ? 0 : -1);
      highlight();
      list.hidden = false;
      place();
      input.setAttribute('aria-expanded', 'true');
    }

    function highlight() {
      Array.prototype.forEach.call(list.children, function (li, i) {
        li.classList.toggle('active', i === active);
        if (i === active) li.scrollIntoView({block: 'nearest'});
      });
    }

    function choose(i) {
      var it = shown[i];
      if (!it) return;
      select.value = it.opt.value;
      select.dispatchEvent(new Event('change', {bubbles: true}));
      showSelected();
      close();
    }

    input.addEventListener('focus', function () { input.select(); render(true); });
    input.addEventListener('input', function () { render(false); });
    toggle.addEventListener('mousedown', function (ev) {   // garder le focus dans le champ
      ev.preventDefault();
      if (!list.hidden) { close(); return; }
      if (document.activeElement === input) render(true); else input.focus();
    });
    input.addEventListener('keydown', function (ev) {
      if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
        ev.preventDefault();
        if (list.hidden) { render(true); return; }
        active = Math.max(0, Math.min(shown.length - 1, active + (ev.key === 'ArrowDown' ? 1 : -1)));
        highlight();
      } else if (ev.key === 'Enter') {
        if (!list.hidden) { ev.preventDefault(); choose(active); }   // ne pas envoyer le formulaire
      } else if (ev.key === 'Escape') {
        if (!list.hidden) { ev.preventDefault(); showSelected(); close(); }
      }
    });
    list.addEventListener('mousedown', function (ev) {   // avant que le champ perde le focus
      var li = ev.target.closest('li[data-i]');
      if (li) { ev.preventDefault(); choose(+li.dataset.i); }
    });
    input.addEventListener('blur', function () {
      if (!input.value.trim() && select.value) {         // champ vidé : plus de produit
        select.value = '';
        select.dispatchEvent(new Event('change', {bubbles: true}));
      }
      showSelected();
      close();
    });
    showSelected();
  }

  window.productPicker = {
    enhance: function (root) {
      (root || document).querySelectorAll('select.product-select').forEach(enhance);
    }
  };
  window.productPicker.enhance();
})();

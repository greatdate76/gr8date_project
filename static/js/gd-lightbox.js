// Lightweight, self-contained lightbox (GR8DATE)
// Activates only on <a data-lightbox="group">...</a> clicks.
(function () {
  const STATE = {
    groups: new Map(), // groupName -> [{link, src, title}]
    currentGroup: null,
    currentIndex: -1,
    overlay: null,
    img: null,
    caption: null,
    prevBtn: null,
    nextBtn: null,
    closeBtn: null,
  };
  function qsa(sel, root = document) { return Array.prototype.slice.call(root.querySelectorAll(sel)); }
  function buildOverlay() {
    if (STATE.overlay) return;
    const overlay = document.createElement('div');
    overlay.className = 'gd-lightbox-overlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.innerHTML = `
      <button class="gd-lightbox-close" aria-label="Close">&times;</button>
      <button class="gd-lightbox-prev" aria-label="Previous">&#10094;</button>
      <button class="gd-lightbox-next" aria-label="Next">&#10095;</button>
      <div class="gd-lightbox-stage">
        <img class="gd-lightbox-img" alt="">
        <div class="gd-lightbox-caption" aria-live="polite"></div>
      </div>
    `;
    document.body.appendChild(overlay);
    STATE.overlay  = overlay;
    STATE.img      = overlay.querySelector('.gd-lightbox-img');
    STATE.caption  = overlay.querySelector('.gd-lightbox-caption');
    STATE.prevBtn  = overlay.querySelector('.gd-lightbox-prev');
    STATE.nextBtn  = overlay.querySelector('.gd-lightbox-next');
    STATE.closeBtn = overlay.querySelector('.gd-lightbox-close');
    overlay.addEventListener('click', (e) => {
      const target = e.target;
      if (target === overlay || target === STATE.closeBtn) hide();
    });
    STATE.prevBtn.addEventListener('click', (e) => { e.stopPropagation(); showIndex(STATE.currentIndex - 1); });
    STATE.nextBtn.addEventListener('click', (e) => { e.stopPropagation(); showIndex(STATE.currentIndex + 1); });
    document.addEventListener('keydown', (e) => {
      if (!STATE.overlay.classList.contains('is-open')) return;
      if (e.key === 'Escape') hide();
      if (e.key === 'ArrowLeft') showIndex(STATE.currentIndex - 1);
      if (e.key === 'ArrowRight') showIndex(STATE.currentIndex + 1);
    });
  }
  function prepareGroups() {
    STATE.groups.clear();
    qsa('a[data-lightbox]').forEach((a) => {
      const group = a.getAttribute('data-lightbox') || '_default';
      const src   = a.getAttribute('href');
      const title = a.getAttribute('data-title') || a.getAttribute('title') || a.querySelector('img')?.getAttribute('alt') || '';
      if (!STATE.groups.has(group)) STATE.groups.set(group, []);
      STATE.groups.get(group).push({ link: a, src, title });
      a.addEventListener('click', (e) => {
        if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        e.preventDefault();
        open(group, src);
      });
    });
  }
  function open(group, src) {
    buildOverlay();
    STATE.currentGroup = group;
    const arr = STATE.groups.get(group) || [];
    const idx = arr.findIndex((it) => it.src === src);
    STATE.overlay.classList.add('is-open');
    document.documentElement.classList.add('gd-lightbox-lock');
    showIndex(idx < 0 ? 0 : idx);
  }
  function hide() {
    STATE.overlay.classList.remove('is-open');
    document.documentElement.classList.remove('gd-lightbox-lock');
    STATE.currentIndex = -1;
  }
  function showIndex(i) {
    const items = STATE.groups.get(STATE.currentGroup) || [];
    if (!items.length) return;
    if (i < 0) i = items.length - 1;
    if (i >= items.length) i = 0;
    STATE.currentIndex = i;
    const { src, title } = items[i];
    STATE.img.src = src;
    STATE.img.alt = title || '';
    STATE.caption.textContent = title || '';
    const multi = items.length > 1;
    STATE.prevBtn.style.display = multi ? '' : 'none';
    STATE.nextBtn.style.display = multi ? '' : 'none';
  }
  document.addEventListener('DOMContentLoaded', () => { prepareGroups(); });
  window.GDLightbox = { refresh: prepareGroups };
})();

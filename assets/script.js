/*
 * JavaScript utilities for the laboratory website.
 *
 * This script implements:
 *  1. A dark/light theme toggle. The user's preference is stored in
 *     localStorage so that returning visitors preserve their theme choice.
 *  2. Dynamic loading of publications from a JSON file and rendering
 *     them into card elements on the page.
 */

(function() {
  /**
   * Initialise the theme based on previously saved preference.
   */
  function initTheme() {
    const htmlEl = document.documentElement;
    const savedTheme = localStorage.getItem('lab-theme');
    if (savedTheme === 'light') {
      htmlEl.classList.add('light');
    }
    const toggleBtn = document.getElementById('themeToggle');
    if (toggleBtn) {
      // Switch the icon between moon and sun depending on current theme
      const updateIcon = () => {
        const icon = toggleBtn.querySelector('i');
        if (!icon) return;
        if (htmlEl.classList.contains('light')) {
          icon.classList.remove('fa-moon');
          icon.classList.add('fa-sun');
        } else {
          icon.classList.remove('fa-sun');
          icon.classList.add('fa-moon');
        }
      };
      updateIcon();
      toggleBtn.addEventListener('click', () => {
        htmlEl.classList.toggle('light');
        const current = htmlEl.classList.contains('light') ? 'light' : 'dark';
        localStorage.setItem('lab-theme', current);
        updateIcon();
      });
    }
  }

  /**
   * Create a publication card element from a publication object.
   *
   * @param {Object} pub
   * @returns {HTMLElement}
   */
  function createPublicationCard(pub) {
    const card = document.createElement('div');
    card.className = 'card';
    // Card header with title and journal badge
    const header = document.createElement('div');
    header.className = 'card-header';
    const titleEl = document.createElement('span');
    titleEl.className = 'card-title';
    titleEl.textContent = pub.title;
    header.appendChild(titleEl);
    if (pub.journal) {
      const badge = document.createElement('span');
      badge.className = 'badge';
      badge.textContent = pub.journal;
      header.appendChild(badge);
    }
    card.appendChild(header);
    // Authors and year
    const meta = document.createElement('div');
    meta.className = 'card-meta';
    const authors = Array.isArray(pub.authors) ? pub.authors.join(', ') : (pub.authors || '');
    meta.textContent = authors + (pub.year ? ' ' + pub.year : '');
    card.appendChild(meta);
    // Buttons container
    const btnContainer = document.createElement('div');
    btnContainer.className = 'card-buttons';
    // ABS button toggles abstract
    const absButton = document.createElement('button');
    absButton.textContent = 'ABS';
    btnContainer.appendChild(absButton);
    // Link to article (if provided)
    if (pub.url) {
      const htmlLink = document.createElement('a');
      htmlLink.textContent = 'HTML';
      htmlLink.href = pub.url;
      htmlLink.target = '_blank';
      btnContainer.appendChild(htmlLink);
    }
    card.appendChild(btnContainer);
    // Abstract container (initially hidden)
    const abstractEl = document.createElement('div');
    abstractEl.className = 'card-abstract';
    abstractEl.textContent = pub.abstract || '';
    card.appendChild(abstractEl);
    // Toggle abstract visibility on click
    absButton.addEventListener('click', () => {
      if (abstractEl.style.display === 'block') {
        abstractEl.style.display = 'none';
      } else {
        abstractEl.style.display = 'block';
      }
    });
    return card;
  }

  /**
   * Fetch publications from the JSON file and render them into the given
   * container element. When `onlySelected` is true, only the first
   * few publications (flagged as selected) are rendered.
   *
   * @param {HTMLElement} container
   * @param {boolean} onlySelected
   */
  function loadPublications(container, onlySelected) {
    fetch('assets/publications.json')
      .then(res => res.json())
      .then(data => {
        if (!Array.isArray(data)) return;
        let pubs = data;
        // Sort by year descending if available
        pubs.sort((a, b) => (b.year || 0) - (a.year || 0));
        if (onlySelected) {
          // Filter to those marked selected or take first 3
          const selected = pubs.filter(p => p.selected);
          pubs = selected.length ? selected : pubs.slice(0, 3);
        }
        pubs.forEach(pub => {
          const card = createPublicationCard(pub);
          container.appendChild(card);
        });
      })
      .catch(err => {
        console.error('Error loading publications:', err);
      });
  }

  // Initialise when DOM is ready
  document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    const selectedContainer = document.getElementById('selected-publications');
    if (selectedContainer) {
      loadPublications(selectedContainer, true);
    }
    const fullContainer = document.getElementById('full-publications');
    if (fullContainer) {
      loadPublications(fullContainer, false);
    }
  });
})();
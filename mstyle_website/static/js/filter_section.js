// Filter Section JavaScript — works with .pc-card (product_grid.html)
document.addEventListener('DOMContentLoaded', function () {

    // Update initial results count
    updateResultsCount(document.querySelectorAll('.pc-card').length);

    // ── Dropdown toggle ───────────────────────────────────────────────────
    document.querySelectorAll('.filter-btn').forEach(function (btn) {
        btn.addEventListener('click', function (e) {
            e.stopPropagation();
            var dropdown = this.nextElementSibling;
            var isOpen = dropdown.classList.contains('show');
            closeAllDropdowns();
            if (!isOpen) {
                dropdown.classList.add('show');
                this.classList.add('active');
            }
        });
    });

    // ── Dropdown item selection ───────────────────────────────────────────
    document.querySelectorAll('.dropdown-item').forEach(function (item) {
        item.addEventListener('click', function (e) {
            e.stopPropagation();
            var dropdown = this.closest('.dropdown-menu');
            var filterBtn = dropdown.previousElementSibling;
            var filterType = dropdown.dataset.filter;

            // Mark active
            dropdown.querySelectorAll('.dropdown-item').forEach(function (i) {
                i.classList.remove('active');
            });
            this.classList.add('active');

            // Update button label
            var btnText = filterBtn && filterBtn.querySelector('.btn-text');
            if (btnText) btnText.textContent = this.textContent.trim();

            closeAllDropdowns();
            applyAllFilters();
        });
    });

    // ── Close on outside click ────────────────────────────────────────────
    document.addEventListener('click', function (e) {
        if (!e.target.closest('.filter-dropdown')) closeAllDropdowns();
    });

    // ── Clear all ─────────────────────────────────────────────────────────
    var clearAllBtn = document.querySelector('.clear-all-btn');
    if (clearAllBtn) {
        clearAllBtn.addEventListener('click', clearAllFilters);
    }

    // ── Remove individual filter tag ──────────────────────────────────────
    document.addEventListener('click', function (e) {
        var tagClose = e.target.closest('.filter-tag i');
        if (tagClose) {
            var tag = tagClose.closest('.filter-tag');
            resetDropdown(tag.dataset.filter);
            applyAllFilters();
        }
    });
});

// ── Core: apply all active filters + sort ────────────────────────────────
function applyAllFilters() {
    var filters = getCurrentFilters();
    var cards = document.querySelectorAll('.pc-card');
    var visibleCount = 0;

    cards.forEach(function (card) {
        var show = true;

        // Category filter
        if (filters.category && filters.category !== 'all') {
            var cardCat = (card.dataset.category || '').toUpperCase().trim();
            var filterCat = filters.category.toUpperCase().trim();
            if (cardCat !== filterCat) show = false;
        }

        card.style.display = show ? '' : 'none';
        if (show) visibleCount++;
    });

    // Sort visible cards
    if (filters.sort && filters.sort !== 'default') {
        sortVisibleCards(filters.sort);
    }

    updateResultsCount(visibleCount);
    updateActiveFilters(filters);
    showEmptyState(visibleCount === 0);
}

// ── Sort visible cards in DOM ─────────────────────────────────────────────
function sortVisibleCards(sortType) {
    var grid = document.querySelector('.product-grid');
    if (!grid) return;

    var visible = Array.from(grid.querySelectorAll('.pc-card')).filter(function (c) {
        return c.style.display !== 'none';
    });

    visible.sort(function (a, b) {
        switch (sortType) {
            case 'price-low':  return parseFloat(a.dataset.price || 0) - parseFloat(b.dataset.price || 0);
            case 'price-high': return parseFloat(b.dataset.price || 0) - parseFloat(a.dataset.price || 0);
            case 'name-az':    return (a.dataset.name || '').localeCompare(b.dataset.name || '');
            case 'name-za':    return (b.dataset.name || '').localeCompare(a.dataset.name || '');
            case 'newest':     return parseFloat(b.dataset.id || 0) - parseFloat(a.dataset.id || 0);
            default:           return 0;
        }
    });

    visible.forEach(function (card) { grid.appendChild(card); });
}

// ── Read current active filter values ────────────────────────────────────
function getCurrentFilters() {
    var filters = {};

    var catActive = document.querySelector('[data-filter="category"] .dropdown-item.active');
    if (catActive) filters.category = catActive.dataset.value || 'all';

    var sortActive = document.querySelector('[data-filter="sort"] .dropdown-item.active');
    if (sortActive) filters.sort = sortActive.dataset.value || 'default';

    return filters;
}

// ── Reset a single dropdown to its default ────────────────────────────────
function resetDropdown(filterType) {
    var dropdown = document.querySelector('[data-filter="' + filterType + '"]');
    if (!dropdown) return;

    dropdown.querySelectorAll('.dropdown-item').forEach(function (i) { i.classList.remove('active'); });

    var def = dropdown.querySelector('[data-value="all"], [data-value="default"]');
    if (def) {
        def.classList.add('active');
        var btn = dropdown.previousElementSibling;
        var btnText = btn && btn.querySelector('.btn-text');
        if (btnText) btnText.textContent = def.textContent.trim();
    }
}

// ── Close all open dropdowns ──────────────────────────────────────────────
function closeAllDropdowns() {
    document.querySelectorAll('.dropdown-menu').forEach(function (m) { m.classList.remove('show'); });
    document.querySelectorAll('.filter-btn').forEach(function (b) { b.classList.remove('active'); });
}

// ── Update results count label ────────────────────────────────────────────
function updateResultsCount(count) {
    var el = document.querySelector('.results-count strong');
    if (el) el.textContent = count;
}

// ── Update active filter tags ─────────────────────────────────────────────
function updateActiveFilters(filters) {
    var container = document.querySelector('.active-filters');
    if (!container) return;

    container.querySelectorAll('.filter-tag').forEach(function (t) { t.remove(); });

    Object.entries(filters).forEach(function (entry) {
        var type = entry[0], value = entry[1];
        if (!value || value === 'all' || value === 'default') return;

        var tag = document.createElement('span');
        tag.className = 'filter-tag';
        tag.dataset.filter = type;

        var label = value;
        if (type === 'sort') {
            var sortEl = document.querySelector('[data-filter="sort"] [data-value="' + value + '"]');
            label = sortEl ? sortEl.textContent.trim() : value;
        } else {
            label = value.charAt(0).toUpperCase() + value.slice(1).toLowerCase();
        }

        tag.innerHTML = label + ' <i class="fas fa-times"></i>';
        var clearBtn = container.querySelector('.clear-all-btn');
        container.insertBefore(tag, clearBtn);
    });

    var clearAllBtn = container.querySelector('.clear-all-btn');
    var hasTags = container.querySelectorAll('.filter-tag').length > 0;
    if (clearAllBtn) clearAllBtn.style.display = hasTags ? 'inline-block' : 'none';
}

// ── Clear all filters ─────────────────────────────────────────────────────
function clearAllFilters() {
    ['category', 'sort'].forEach(resetDropdown);

    document.querySelectorAll('.pc-card').forEach(function (c) { c.style.display = ''; });

    updateResultsCount(document.querySelectorAll('.pc-card').length);
    updateActiveFilters({});
    showEmptyState(false);
}

// ── Empty state ───────────────────────────────────────────────────────────
function showEmptyState(show) {
    var grid = document.querySelector('.product-grid');
    if (!grid) return;

    var existing = grid.querySelector('.filter-empty-state');
    if (existing) existing.remove();

    if (show) {
        var el = document.createElement('div');
        el.className = 'filter-empty-state';
        el.style.cssText = 'grid-column:1/-1;text-align:center;padding:3rem 1rem;color:#6c757d;';
        el.innerHTML = '<i class="fas fa-search" style="font-size:3rem;color:#dee2e6;display:block;margin-bottom:1rem;"></i>'
            + '<h3 style="color:#2c3e50;margin-bottom:.5rem;">No Products Found</h3>'
            + '<p>No products match your current filters.</p>'
            + '<button onclick="clearAllFilters()" style="margin-top:1rem;padding:.6rem 1.4rem;background:linear-gradient(135deg,#1a1a1a,#2c3e50);color:#fff;border:none;border-radius:8px;cursor:pointer;font-weight:600;">'
            + '<i class="fas fa-redo"></i> Clear Filters</button>';
        grid.appendChild(el);
    }
}

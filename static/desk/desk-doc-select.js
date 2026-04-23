/**
 * Replace native single <select> on desk document forms with Tom Select
 * (custom dropdown list + styling consistent with the rest of the desk).
 */
(function () {
  function initDeskDocSelects() {
    if (typeof TomSelect === 'undefined') {
      return;
    }
    document.querySelectorAll('.desk-doc-form select.desk-modal-select:not([multiple])').forEach(function (el) {
      if (el.disabled || el.getAttribute('data-desk-no-tomselect') === '1') {
        return;
      }
      if (el.tomselect) {
        return;
      }
      try {
        new TomSelect(el, {
          allowEmptyOption: true,
          create: false,
          maxOptions: null,
          dropdownParent: 'body',
          hidePlaceholder: false,
        });
      } catch (e) {
        /* e.g. already wrapped */
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initDeskDocSelects);
  } else {
    initDeskDocSelects();
  }
})();

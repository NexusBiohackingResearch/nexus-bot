(function () {
  const status = document.getElementById('status-message');
  const walletButton = document.getElementById('wallet-button');

  function showStatus(message, error) {
    status.textContent = message;
    status.style.color = error ? '#ff8295' : '#7dfb77';
    window.setTimeout(() => { status.textContent = ''; }, 3500);
  }

  async function copyValue(value, successMessage) {
    try {
      await navigator.clipboard.writeText(value);
      showStatus(successMessage, false);
    } catch (_) {
      const area = document.createElement('textarea');
      area.value = value;
      area.style.position = 'fixed';
      area.style.opacity = '0';
      document.body.appendChild(area);
      area.select();
      const ok = document.execCommand('copy');
      area.remove();
      showStatus(ok ? successMessage : 'Copie impossible. Sélectionnez la valeur manuellement.', !ok);
    }
  }

  document.querySelectorAll('[data-copy]').forEach((button) => {
    button.addEventListener('click', () => {
      copyValue(button.dataset.copy, button.dataset.success || 'Copié.');
    });
  });

  walletButton.addEventListener('click', () => {
    const original = walletButton.innerHTML;
    walletButton.innerHTML = '<span>↗</span><span>Ouverture du portefeuille…</span>';
    showStatus('Vérifiez soigneusement le montant et l’adresse avant de confirmer.', false);
    window.setTimeout(() => { walletButton.innerHTML = original; }, 3000);
  });
})();

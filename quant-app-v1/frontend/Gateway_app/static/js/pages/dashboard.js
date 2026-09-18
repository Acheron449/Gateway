document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.sidebar-menu li').forEach(item => {
    item.addEventListener('click', () => {
      document.querySelectorAll('.sidebar-menu li').forEach(i => i.classList.remove('active'));
      item.classList.add('active');
      const section = item.dataset.section;
      document.querySelectorAll('.section').forEach(s => s.classList.toggle('active', s.id === section));
    });
  });

  async function loadAccount() {
    const response = await fetch('/api/account');
    if (!response.ok) {
      window.location.href = '/';
      return;
    }

    const data = await response.json();
    document.getElementById('accName').textContent = data.name || '-';
    document.getElementById('accLastName').textContent = data.last_name || '-';
    document.getElementById('accEmail').textContent = data.email || '-';
    document.getElementById('accCredits').textContent = data.meta?.credits ?? '-';
    document.getElementById('accUsage').textContent = data.meta?.usage_remaining ?? '-';

    document.getElementById('fieldName').value = data.name || '';
    document.getElementById('fieldLastName').value = data.last_name || '';
    document.getElementById('fieldEmail').value = data.email || '';
    document.getElementById('fieldPayment').value = JSON.stringify(data.meta?.payment || {}, null, 2);
    document.getElementById('fieldApiInputs').value = JSON.stringify(data.meta?.api_inputs || {}, null, 2);
  }

  function showMessage(id, type, message) {
    const element = document.getElementById(id);
    if (!element) return;
    element.textContent = message;
    element.classList.remove('success', 'error');
    if (type === 'success') element.classList.add('success');
    if (type === 'error') element.classList.add('error');
  }

  document.getElementById('accountForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    showMessage('accountMsg', '', '');
    const payload = {
      name: document.getElementById('fieldName').value.trim(),
      last_name: document.getElementById('fieldLastName').value.trim(),
      email: document.getElementById('fieldEmail').value.trim()
    };

    const response = await fetch('/api/account', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await response.json().catch(() => ({}));

    if (response.status === 200) {
      showMessage('accountMsg', 'success', 'Saved');
      loadAccount();
    } else if (response.status === 202) {
      showMessage('accountMsg', 'success', data.message || 'Confirmation required');
      document.getElementById('emailConfirmSection').style.display = 'block';
      document.getElementById('emailToken').value = data.confirmation_token || '';
      document.getElementById('emailConfirmMsg').textContent = 'Paste token and press Confirm to apply the email change.';
    } else {
      showMessage('accountMsg', 'error', data.message || 'Failed to save');
    }
  });

  document.getElementById('confirmEmailBtn')?.addEventListener('click', async () => {
    const token = document.getElementById('emailToken').value.trim();
    if (!token) return showMessage('emailConfirmMsg', 'error', 'Token required');
    const response = await fetch('/api/account/confirm_email', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token })
    });
    const data = await response.json().catch(() => ({}));
    if (response.ok) {
      showMessage('emailConfirmMsg', 'success', 'Email confirmed.');
      document.getElementById('emailConfirmSection').style.display = 'none';
      loadAccount();
    } else {
      showMessage('emailConfirmMsg', 'error', data.message || 'Failed to confirm');
    }
  });

  document.getElementById('paymentForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    showMessage('paymentMsg', '', '');
    let payment = {};
    try {
      payment = JSON.parse(document.getElementById('fieldPayment').value || '{}');
    } catch (error) {
      showMessage('paymentMsg', 'error', 'Invalid JSON');
      return;
    }

    const response = await fetch('/api/account', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ payment })
    });
    const data = await response.json().catch(() => ({}));
    if (response.ok) {
      showMessage('paymentMsg', 'success', 'Saved');
    } else {
      showMessage('paymentMsg', 'error', data.message || 'Failed to save');
    }
  });

  document.getElementById('topupForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    showMessage('topupMsg', '', '');
    const amount = document.getElementById('fieldTopup').value;
    const response = await fetch('/api/billing/topup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ amount })
    });
    const data = await response.json().catch(() => ({}));
    if (response.ok) {
      showMessage('topupMsg', 'success', `Added ${data.added_credits} credits. Total: ${data.credits}`);
      loadAccount();
    } else {
      showMessage('topupMsg', 'error', data.message || 'Top-up failed');
    }
  });

  document.getElementById('apiForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    showMessage('apiMsg', '', '');
    let apiInputs = {};
    try {
      apiInputs = JSON.parse(document.getElementById('fieldApiInputs').value || '{}');
    } catch (error) {
      showMessage('apiMsg', 'error', 'Invalid JSON');
      return;
    }

    const response = await fetch('/api/account', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_inputs: apiInputs })
    });
    const data = await response.json().catch(() => ({}));
    if (response.ok) {
      showMessage('apiMsg', 'success', 'Saved');
    } else {
      showMessage('apiMsg', 'error', data.message || 'Failed to save');
    }
  });

  document.getElementById('logoutBtn')?.addEventListener('click', async () => {
    await fetch('/api/auth/logout', { method: 'POST' });
    window.location.href = '/';
  });

  loadAccount();
});

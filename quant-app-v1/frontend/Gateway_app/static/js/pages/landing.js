document.addEventListener('DOMContentLoaded', () => {
  const authOverlay = document.getElementById('authOverlay');
  const authTabs = document.querySelectorAll('.auth-tab');
  const authForms = document.querySelectorAll('.auth-form');
  const authToggleButtons = document.querySelectorAll('.auth-toggle');
  const authClose = document.querySelector('.auth-close');
  const authFeedback = document.getElementById('authFeedback');
  const loginForm = document.getElementById('loginForm');
  const signupForm = document.getElementById('signupForm');
  const promptInput = document.getElementById('promptInput');
  const generateBtn = document.getElementById('generatePlanBtn');
  const newsList = document.getElementById('newsList');

  function setAuthMessage(type, message) {
    if (!authFeedback) return;
    authFeedback.textContent = message;
    authFeedback.classList.remove('success', 'error');
    if (type === 'success') authFeedback.classList.add('success');
    if (type === 'error') authFeedback.classList.add('error');
  }

  function clearAuthMessage() {
    if (!authFeedback) return;
    authFeedback.textContent = '';
    authFeedback.classList.remove('success', 'error');
  }

  function setAuthMode(mode) {
    clearAuthMessage();
    authTabs.forEach(tab => tab.classList.toggle('active', tab.dataset.mode === mode));
    authForms.forEach(form => form.classList.toggle('active', form.id === `${mode}Form`));
  }

  function openAuth(mode = 'login') {
    if (!authOverlay) return;
    authOverlay.classList.add('visible');
    authOverlay.setAttribute('aria-hidden', 'false');
    setAuthMode(mode);
  }

  function closeAuth() {
    if (!authOverlay) return;
    authOverlay.classList.remove('visible');
    authOverlay.setAttribute('aria-hidden', 'true');
    clearAuthMessage();
  }

  authTabs.forEach(tab => tab.addEventListener('click', () => setAuthMode(tab.dataset.mode)));
  authToggleButtons.forEach(button => button.addEventListener('click', () => openAuth(button.dataset.mode)));
  authClose?.addEventListener('click', closeAuth);
  authOverlay?.addEventListener('click', (event) => {
    if (event.target === authOverlay) closeAuth();
  });

  const submitPrompt = async () => {
    const prompt = (promptInput?.value || '').trim();
    const resultsPanel = document.getElementById('resultsPanel');
    if (!prompt) return;

    try {
      const response = await fetch('/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || 'Generate failed');
      const metrics = data.metrics || {};
      document.getElementById('winRate').textContent = metrics.win_rate || '--';
      document.getElementById('drawdown').textContent = metrics.drawdown || '--';
      document.getElementById('trades').textContent = metrics.trades || '--';
      document.getElementById('profitFactor').textContent = metrics.profit_factor || '--';
      resultsPanel?.classList.remove('hidden');
    } catch (error) {
      console.error(error);
      resultsPanel?.classList.remove('hidden');
      document.getElementById('winRate').textContent = 'Error';
      document.getElementById('drawdown').textContent = '--';
      document.getElementById('trades').textContent = '--';
      document.getElementById('profitFactor').textContent = '--';
    }
  };

  window.submitPrompt = submitPrompt;
  window.setPrompt = (value) => {
    if (promptInput) {
      promptInput.value = value;
    }
  };

  generateBtn?.addEventListener('click', submitPrompt);

  loginForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const email = document.getElementById('loginEmail')?.value?.trim() || '';
    const password = document.getElementById('loginPassword')?.value || '';

    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password })
      });
      const data = await response.json();
      if (!response.ok) {
        setAuthMessage('error', data.error || data.message || 'Login failed');
        return;
      }
      setAuthMessage('success', data.message || 'Login successful');
      // close the modal then navigate so the UI feels responsive
      closeAuth();
      // small delay so the close animation can run if present
      setTimeout(() => { window.location.assign(data.redirect || '/main'); }, 120);
    } catch (error) {
      setAuthMessage('error', 'Login failed');
    }
  });

  signupForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const payload = {
      name: document.getElementById('signupFirstName')?.value?.trim() || '',
      last_name: document.getElementById('signupLastName')?.value?.trim() || '',
      email: document.getElementById('signupEmail')?.value?.trim() || '',
      password: document.getElementById('signupPassword')?.value || ''
    };

    try {
      const response = await fetch('/api/auth/signup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await response.json();
      if (!response.ok) {
        setAuthMessage('error', data.error || data.message || 'Signup failed');
        return;
      }
      setAuthMessage('success', data.message || 'Account created');
      closeAuth();
      setTimeout(() => { window.location.assign('/main'); }, 120);
    } catch (error) {
      setAuthMessage('error', 'Signup failed');
    }
  });

  async function refreshAuthUI() {
    try {
      const response = await fetch('/api/auth/me');
      const data = await response.json();
      const navActions = document.querySelector('.nav-actions');
      if (!navActions) return;

      if (data.logged_in || data.authenticated) {
        let credits = 0;
        let usageRemaining = 0;
        try {
          const accountRes = await fetch('/api/account');
          const accountData = accountRes.ok ? await accountRes.json() : null;
          credits = Number(accountData?.meta?.credits ?? 0);
          usageRemaining = Number(accountData?.meta?.usage_remaining ?? 0);
          const displayName = [accountData?.name, accountData?.last_name].filter(Boolean).join(' ') || data.user?.name || data.user?.email || 'Trader';
          navActions.innerHTML = `<a href="/dashboard" class="user-badge" id="userBadge">Hi, ${displayName}</a><span class="credit-badge">${credits} credits</span><button class="btn-ghost" id="logoutBtn">Log Out</button>`;
        } catch (error) {
          const displayName = data.user?.name || data.user?.email || 'Trader';
          navActions.innerHTML = `<a href="/dashboard" class="user-badge" id="userBadge">Hi, ${displayName}</a><span class="credit-badge">0 credits</span><button class="btn-ghost" id="logoutBtn">Log Out</button>`;
        }

        const logoutBtn = document.getElementById('logoutBtn');
        logoutBtn?.addEventListener('click', async () => {
          await fetch('/api/auth/logout', { method: 'POST' });
          refreshAuthUI();
          openAuth('login');
        });

        const generateButton = document.getElementById('generatePlanBtn');
        if (generateButton) {
          generateButton.disabled = usageRemaining <= 0;
          generateButton.title = usageRemaining <= 0 ? 'No credits remaining' : 'Generate your trading plan';
          generateButton.textContent = usageRemaining <= 0 ? 'No Credits Left' : 'Generate Plan';
        }

        closeAuth();
      } else {
        navActions.innerHTML = `<button type="button" class="btn-ghost auth-toggle" data-mode="login">Log In</button><button type="button" class="btn-primary auth-toggle" data-mode="signup">Sign Up</button>`;
        document.querySelectorAll('.auth-toggle').forEach(button => button.addEventListener('click', () => openAuth(button.dataset.mode)));
        const generateButton = document.getElementById('generatePlanBtn');
        if (generateButton) {
          generateButton.disabled = false;
          generateButton.textContent = 'Generate Plan';
        }
        closeAuth();
      }
    } catch (error) {
      console.error('Auth refresh failed', error);
    }
  }

  async function loadNews() {
    if (!newsList) return;
    try {
      const response = await fetch('/api/news/forex-factory?limit=5');
      const data = await response.json();
      const items = Array.isArray(data) ? data : (data.items || []);
      if (!items.length) {
        newsList.innerHTML = '<div class="news-card"><h3>Forex Factory</h3><p>No news available right now.</p></div>';
        return;
      }

      newsList.innerHTML = items.map(item => `
        <article class="news-card">
          <div class="news-meta">${item.source || 'Forex Factory'} • ${item.published_at ? new Date(item.published_at).toLocaleDateString() : 'Today'}</div>
          <h3>${(item.title || item.headline || 'Market Update').replace(/</g, '&lt;')}</h3>
          <p>${(item.summary || item.headline || '').slice(0, 180)}${(item.summary || item.headline || '').length > 180 ? '…' : ''}</p>
          <a href="${item.url || '#'}" target="_blank" rel="noreferrer">Read more</a>
        </article>
      `).join('');
    } catch (error) {
      console.error('News load failed', error);
      newsList.innerHTML = '<div class="news-card"><h3>Forex Factory</h3><p>News feed is temporarily unavailable.</p></div>';
    }
  }

  refreshAuthUI();
  loadNews();
});

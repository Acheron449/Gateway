(function () {
  const page = document.body && document.body.dataset.page;
  if (!page) return;

  function initLandingPage() {
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
      if (promptInput) promptInput.value = value;
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
        closeAuth();
        setTimeout(() => {
          window.location.assign(data.redirect || '/main');
        }, 120);
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
        setTimeout(() => {
          window.location.assign('/main');
        }, 120);
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
  }

  function initDashboardPage() {
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
        const emailConfirmSection = document.getElementById('emailConfirmSection');
        if (emailConfirmSection) emailConfirmSection.style.display = 'block';
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
        const emailConfirmSection = document.getElementById('emailConfirmSection');
        if (emailConfirmSection) emailConfirmSection.style.display = 'none';
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
  }

  function initMainPage() {
    const DEFAULT_SYMBOL = 'EURUSD';
    let currentSymbol = DEFAULT_SYMBOL;
    let currentTF = '1h';
    let candleSeries;
    let miniSeries;
    let chart;
    let miniChart;
    let ws;

    function tfToSeconds(tf) {
      return tf === '1m' ? 60 : tf === '5m' ? 300 : tf === '15m' ? 900 : tf === '1h' ? 3600 : tf === '4h' ? 14400 : 86400;
    }

    async function loadHistory(symbol = DEFAULT_SYMBOL, tf = '1h', limit = 500) {
      const response = await fetch(`/api/market/history?symbol=${encodeURIComponent(symbol)}&tf=${encodeURIComponent(tf)}&limit=${limit}`);
      if (!response.ok) throw new Error('History fetch failed');
      const data = await response.json();
      const candles = Array.isArray(data) ? data : (Array.isArray(data.candles) ? data.candles : []);
      return candles.map(item => ({ time: item.time, open: item.open, high: item.high, low: item.low, close: item.close }));
    }

    function setupTimeframeButtons() {
      document.querySelectorAll('.tf-btn').forEach(button => {
        button.addEventListener('click', async () => {
          currentTF = button.dataset.tf || currentTF;
          document.querySelectorAll('.tf-btn').forEach(btn => btn.classList.remove('active'));
          button.classList.add('active');
          subscribeToCurrentMarket();
          await refreshChartData();
        });
      });

      const activeButton = document.querySelector('.tf-btn[data-tf="1h"]');
      activeButton?.classList.add('active');
    }

    function setupSymbolControls() {
      const searchInput = document.getElementById('symbolSearch');
      const applySymbol = (value) => {
        const symbol = (value || '').trim().toUpperCase();
        if (!symbol) return;
        currentSymbol = symbol;
        refreshChartData();
      };

      searchInput?.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') applySymbol(searchInput.value);
      });

      document.querySelectorAll('.watchlist li').forEach(item => {
        item.addEventListener('click', () => applySymbol(item.textContent.trim()));
      });
    }

    function subscribeToCurrentMarket() {
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      try { ws.send(JSON.stringify({ action: 'unsubscribe', symbol: currentSymbol, tf: currentTF })); } catch (error) {}
      try { ws.send(JSON.stringify({ action: 'subscribe', symbol: currentSymbol, tf: currentTF })); } catch (error) {}
    }

    async function refreshChartData() {
      try {
        const data = await loadHistory(currentSymbol, currentTF, 800);
        if (!data || !data.length) return;
        candleSeries.setData(data);
        miniSeries.setData(data.map(d => ({ time: d.time, value: d.close })));
        chart.timeScale().fitContent();
        miniChart.timeScale().fitContent();
        const chartTitle = document.getElementById('chartTitle');
        if (chartTitle) chartTitle.textContent = `${currentSymbol} · ${currentTF}`;
        subscribeToCurrentMarket();
      } catch (error) {
        console.warn('Chart data error', error);
      }
    }

    function setupWebSocket() {
      try {
        const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
        ws = new WebSocket(`${scheme}://${location.host}/ws/trading`);
        ws.onopen = () => {
          console.debug('WS open');
          subscribeToCurrentMarket();
        };
        ws.onmessage = (event) => {
          try {
            const message = JSON.parse(event.data);
            if ((message.type === 'candle_update' || message.type === 'candle_closed') && message.symbol === currentSymbol && message.tf === currentTF) {
              const candle = message.candle;
              if (candle && candleSeries) {
                candleSeries.update({ time: candle.time, open: candle.open, high: candle.high, low: candle.low, close: candle.close });
                miniSeries.update({ time: candle.time, value: candle.close });
              }
              return;
            }

            const price = Number(message.price);
            if (!price || !candleSeries) return;
            const nowSec = Math.floor(Date.now() / 1000);
            const step = tfToSeconds(currentTF);
            const bucket = Math.floor(nowSec / step) * step;
            const last = window._lastCandle;
            if (last && last.time === bucket) {
              last.close = price;
              last.high = Math.max(last.high, price);
              last.low = Math.min(last.low, price);
              candleSeries.update(last);
              miniSeries.update({ time: last.time, value: last.close });
            } else {
              const prevClose = last ? last.close : price;
              const nextCandle = { time: bucket, open: prevClose, high: Math.max(prevClose, price), low: Math.min(prevClose, price), close: price };
              window._lastCandle = nextCandle;
              candleSeries.update(nextCandle);
              miniSeries.update({ time: nextCandle.time, value: nextCandle.close });
            }
          } catch (error) {
            console.warn('WS data parse failed', error);
          }
        };
      } catch (error) {
        console.warn('WebSocket setup failed', error);
      }
    }

    async function initCharts() {
      const mainEl = document.getElementById('mainChart');
      const miniEl = document.getElementById('miniChart');
      if (!mainEl || !miniEl || !window.LightweightCharts) return;

      mainEl.innerHTML = '';
      miniEl.innerHTML = '';

      chart = LightweightCharts.createChart(mainEl, {
        layout: { backgroundColor: '#071019', textColor: '#d1e2ff' },
        rightPriceScale: { borderVisible: false },
        timeScale: { borderVisible: false }
      });
      candleSeries = chart.addCandlestickSeries();

      miniChart = LightweightCharts.createChart(miniEl, {
        layout: { backgroundColor: '#071019', textColor: '#94a3b8' },
        handleScale: false,
        handleScroll: false,
        rightPriceScale: { visible: false },
        timeScale: { visible: true }
      });
      miniSeries = miniChart.addAreaSeries({
        topColor: 'rgba(0,230,153,0.2)',
        bottomColor: 'rgba(0,230,153,0.0)',
        lineColor: 'rgba(0,230,153,0.8)',
        lineWidth: 1
      });

      miniChart.timeScale().subscribeVisibleTimeRangeChange(range => {
        if (range) chart.timeScale().setVisibleRange(range);
      });

      await refreshChartData();
      setupWebSocket();
    }

    const strategyPrompt = document.getElementById('strategyPrompt');
    const strategyResults = document.getElementById('strategyResults');
    const generateStrategyBtn = document.getElementById('generateStrategyBtn');

    generateStrategyBtn?.addEventListener('click', async () => {
      const prompt = (strategyPrompt?.value || '').trim();
      if (!prompt) return;
      const response = await fetch('/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt })
      });
      const data = await response.json();
      const summary = data.data?.summary || 'Strategy created';
      strategyResults.innerHTML = `<div class="strategy-result"><strong>Strategy generated</strong><p>${summary}</p></div>`;
    });

    document.getElementById('logoutBtnTop')?.addEventListener('click', async () => {
      await fetch('/api/auth/logout', { method: 'POST' });
      window.location.href = '/';
    });

    document.getElementById('openBacktest')?.addEventListener('click', async () => {
      try {
        const bars = await loadHistory(currentSymbol, currentTF, 500);
        const payload = { bars: bars.map(b => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close })) };
        const resp = await fetch('/api/backtest', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'Backtest failed');
        const analysis = data.analysis || {};
        const resultsEl = document.getElementById('strategyResults');
        if (resultsEl) {
          resultsEl.innerHTML = `<div class="backtest-summary">
            <h4>Backtest Results</h4>
            <p>Trades: ${analysis.trades_count}</p>
            <p>Win Rate: ${analysis.win_rate}%</p>
            <p>Avg PnL: ${analysis.avg_pnl_pct}%</p>
            <p>Total PnL: ${analysis.total_pnl_pct}%</p>
            <p>Max Drawdown: ${analysis.max_drawdown_pct}%</p>
            <div class="backtest-trades">${(analysis.trades || []).map(t => `<div class="trade">${t.entry_time} → ${t.exit_time} : ${t.pnl_pct ? t.pnl_pct.toFixed(3) : 'N/A'}%</div>`).join('')}</div>
          </div>`;
        } else {
          alert(JSON.stringify(analysis, null, 2));
        }
      } catch (err) {
        console.error('Backtest error', err);
        alert('Backtest failed: ' + (err.message || err));
      }
    });

    setupTimeframeButtons();
    setupSymbolControls();
    initCharts();
  }

  document.addEventListener('DOMContentLoaded', () => {
    if (page === 'landing') initLandingPage();
    else if (page === 'dashboard') initDashboardPage();
    else if (page === 'main') initMainPage();
  });
})();

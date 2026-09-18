document.addEventListener('DOMContentLoaded', () => {
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
    return (data || []).map(item => ({ time: item.time, open: item.open, high: item.high, low: item.low, close: item.close }));
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
      if (event.key === 'Enter') {
        applySymbol(searchInput.value);
      }
    });

    document.querySelectorAll('.watchlist li').forEach(item => {
      item.addEventListener('click', () => applySymbol(item.textContent.trim()));
    });
  }

  function subscribeToCurrentMarket() {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    try {
      ws.send(JSON.stringify({ action: 'unsubscribe', symbol: currentSymbol, tf: currentTF }));
    } catch (error) {}
    try {
      ws.send(JSON.stringify({ action: 'subscribe', symbol: currentSymbol, tf: currentTF }));
    } catch (error) {}
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

  // Backtest runner: fetch history, POST to /api/backtest, and display summary
  document.getElementById('openBacktest')?.addEventListener('click', async () => {
    try {
      const bars = await loadHistory(currentSymbol, currentTF, 500);
      const payload = { bars: bars.map(b => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close })) };
      const resp = await fetch('/api/backtest', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || 'Backtest failed');
      const analysis = data.analysis || data.analysis || {};
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
});

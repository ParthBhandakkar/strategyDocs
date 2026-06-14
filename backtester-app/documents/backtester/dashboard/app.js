// Dashboard State
let strategies = [];
let activeStrategyId = null;
let activeStrategyUrl = null;
let currentRunData = null;
let equityChart = null;

const API_BASE = 'http://127.0.0.1:8000/api';

// Initialize
document.addEventListener('DOMContentLoaded', async () => {
    // Setup Tabs
    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.tab, .tab-content').forEach(el => el.classList.remove('active'));
            tab.classList.add('active');
            document.getElementById(tab.dataset.target).classList.add('active');
        });
    });

    // Setup Config Button
    document.getElementById('btn-config').addEventListener('click', openConfigModal);

    // Setup Run Button
    document.getElementById('btn-run-backtest').addEventListener('click', runBacktest);

    // Load initial data
    await loadSymbols();
    await loadStrategies();
});

// API Calls
async function loadStrategies() {
    try {
        const res = await fetch(`${API_BASE}/strategies`);
        const data = await res.json();
        strategies = data.strategies;
        renderStrategyList();
    } catch (e) {
        console.error('Failed to load strategies', e);
    }
}

async function loadSymbols() {
    try {
        const res = await fetch(`${API_BASE}/data/symbols`);
        const data = await res.json();
        const select = document.getElementById('config-symbol');
        data.symbols.forEach(sym => {
            const opt = document.createElement('option');
            opt.value = sym;
            opt.textContent = sym;
            select.appendChild(opt);
        });
    } catch (e) {
        console.error('Failed to load symbols', e);
    }
}

async function selectStrategy(id) {
    activeStrategyId = id;
    
    // Update active class in sidebar
    document.querySelectorAll('.strategy-card').forEach(card => {
        card.classList.toggle('active', card.dataset.id === id);
    });

    try {
        const res = await fetch(`${API_BASE}/strategies/${id}`);
        const data = await res.json();
        
        activeStrategyUrl = data.video_url;
        
        // Update header
        document.getElementById('active-strategy-title').textContent = data.name;
        document.getElementById('btn-video').disabled = false;
        document.getElementById('btn-config').disabled = false;
        
        const badgesContainer = document.getElementById('active-strategy-badges');
        badgesContainer.innerHTML = '';
        data.timeframes.forEach(tf => {
            const badge = document.createElement('span');
            badge.className = 'badge';
            badge.textContent = tf;
            badgesContainer.appendChild(badge);
        });

        renderPlaybook(data.playbook);
    } catch (e) {
        console.error('Failed to load playbook', e);
    }
}

// Rendering
function renderStrategyList() {
    const list = document.getElementById('strategy-list');
    list.innerHTML = '';
    
    strategies.forEach(strat => {
        const div = document.createElement('div');
        div.className = 'strategy-card';
        div.dataset.id = strat.id;
        div.innerHTML = `
            <h3>${strat.name}</h3>
            <p>${strat.description}</p>
            <div>
                ${strat.timeframes.map(tf => `<span class="badge">${tf}</span>`).join('')}
            </div>
        `;
        div.addEventListener('click', () => selectStrategy(strat.id));
        list.appendChild(div);
    });
}

function renderPlaybook(steps) {
    const container = document.getElementById('playbook-container');
    container.innerHTML = '';
    
    steps.forEach(step => {
        const conditionsHtml = step.conditions && step.conditions.length > 0 
            ? `<div class="step-conditions"><ul>${step.conditions.map(c => `<li>${c}</li>`).join('')}</ul></div>` 
            : '';
            
        const div = document.createElement('div');
        div.className = 'step-card';
        div.innerHTML = `
            <div class="step-header">
                <div class="step-number">${step.step_number}</div>
                <div class="step-title">${step.title} <span class="badge" style="margin-left:10px; margin-top:0;">${step.timeframe}</span></div>
            </div>
            <div class="step-desc">${step.description}</div>
            ${conditionsHtml}
        `;
        container.appendChild(div);
    });
}

// Modals
function openConfigModal() {
    // Set default dates (last 30 days)
    const end = new Date();
    const start = new Date();
    start.setDate(start.getDate() - 30);
    
    document.getElementById('config-end').value = end.toISOString().split('T')[0];
    document.getElementById('config-start').value = start.toISOString().split('T')[0];
    
    document.getElementById('config-modal').classList.add('active');
}

function closeModal(id) {
    document.getElementById(id).classList.remove('active');
}

// Backtest Execution
async function runBacktest() {
    if (!activeStrategyId) return;

    const btn = document.getElementById('btn-run-backtest');
    const text = document.getElementById('run-text');
    
    btn.disabled = true;
    text.textContent = 'Running...';
    
    const payload = {
        strategy_id: activeStrategyId,
        symbol: document.getElementById('config-symbol').value,
        start_date: document.getElementById('config-start').value + 'T00:00:00Z',
        end_date: document.getElementById('config-end').value + 'T23:59:59Z',
        initial_balance: parseFloat(document.getElementById('config-balance').value),
        risk_per_trade: parseFloat(document.getElementById('config-risk').value) / 100.0,
    };

    try {
        const res = await fetch(`${API_BASE}/backtest/run`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        const data = await res.json();
        
        if (data.status === 'success') {
            await fetchResults(data.run_id);
            closeModal('config-modal');
            // Switch to results tab
            document.querySelector('[data-target="results-tab"]').click();
        } else {
            alert('Backtest failed: ' + JSON.stringify(data));
        }
    } catch (e) {
        alert('Error connecting to server.');
        console.error(e);
    } finally {
        btn.disabled = false;
        text.textContent = 'Start Backtest';
    }
}

async function fetchResults(runId) {
    try {
        const res = await fetch(`${API_BASE}/backtest/${runId}/results`);
        currentRunData = await res.json();
        renderResultsDashboard();
    } catch (e) {
        console.error('Failed to fetch results', e);
    }
}

function renderResultsDashboard() {
    const stats = currentRunData.stats;
    
    document.getElementById('results-empty').style.display = 'none';
    document.getElementById('results-dashboard').style.display = 'block';
    
    // Stats
    const pnlEl = document.getElementById('stat-pnl');
    pnlEl.textContent = `$${stats.total_pnl.toFixed(2)}`;
    pnlEl.className = 'stat-value ' + (stats.total_pnl >= 0 ? 'positive' : 'negative');
    
    document.getElementById('stat-winrate').textContent = `${stats.win_rate}%`;
    document.getElementById('stat-pf').textContent = stats.profit_factor === 'inf' ? 'INF' : stats.profit_factor.toFixed(2);
    document.getElementById('stat-dd').textContent = `${stats.max_drawdown_pct}%`;
    
    // Chart
    renderEquityChart(currentRunData.equity_curve);
    
    // Trades Table
    const tbody = document.getElementById('trades-tbody');
    tbody.innerHTML = '';
    
    currentRunData.trades.forEach((trade, idx) => {
        const tr = document.createElement('tr');
        const entryDate = new Date(trade.entry_time).toLocaleString();
        
        tr.innerHTML = `
            <td>${trade.id}</td>
            <td>${entryDate}</td>
            <td class="${trade.direction === 'LONG' ? 'dir-long' : 'dir-short'}">${trade.direction}</td>
            <td>${trade.entry_price.toFixed(5)}</td>
            <td>${trade.exit_price ? trade.exit_price.toFixed(5) : '--'}</td>
            <td class="${trade.pnl >= 0 ? 'dir-long' : 'dir-short'}">$${trade.pnl.toFixed(2)}</td>
            <td>${trade.rr_achieved.toFixed(2)}R</td>
            <td><button class="btn btn-secondary" style="padding: 5px 10px; font-size: 0.8rem;" onclick="openTradeInspector(${idx})">Inspect</button></td>
        `;
        tbody.appendChild(tr);
    });
}

function renderEquityChart(curveData) {
    const ctx = document.getElementById('equityChart').getContext('2d');
    
    if (equityChart) {
        equityChart.destroy();
    }
    
    const labels = curveData.map(d => new Date(d.time).toLocaleDateString());
    const data = curveData.map(d => d.equity);
    
    equityChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Account Equity ($)',
                data: data,
                borderColor: '#4361ee',
                backgroundColor: 'rgba(67, 97, 238, 0.1)',
                borderWidth: 2,
                pointRadius: 0,
                fill: true,
                tension: 0.1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }
            },
            scales: {
                y: {
                    grid: { color: '#2e3047' },
                    ticks: { color: '#94a3b8' }
                },
                x: {
                    grid: { display: false },
                    ticks: { color: '#94a3b8', maxTicksLimit: 10 }
                }
            }
        }
    });
}

// Trade Inspector
function openTradeInspector(tradeIdx) {
    const trade = currentRunData.trades[tradeIdx];
    
    document.getElementById('insp-trade-id').textContent = `#${trade.id}`;
    document.getElementById('insp-direction').textContent = trade.direction;
    document.getElementById('insp-direction').className = 'd-value ' + (trade.direction === 'LONG' ? 'dir-long' : 'dir-short');
    
    document.getElementById('insp-entry').textContent = trade.entry_price.toFixed(5);
    document.getElementById('insp-exit').textContent = trade.exit_price ? trade.exit_price.toFixed(5) : 'Open';
    
    document.getElementById('insp-pnl').textContent = trade.pnl.toFixed(2);
    document.getElementById('insp-pnl').style.color = trade.pnl >= 0 ? 'var(--accent-green)' : 'var(--accent-red)';
    
    document.getElementById('insp-rr').textContent = trade.rr_achieved.toFixed(2) + 'R';
    
    // Duration
    if (trade.exit_time) {
        const mins = (new Date(trade.exit_time) - new Date(trade.entry_time)) / 60000;
        document.getElementById('insp-duration').textContent = `${Math.round(mins)} mins`;
    } else {
        document.getElementById('insp-duration').textContent = '--';
    }
    
    // Timeline
    const tl = document.getElementById('insp-timeline');
    tl.innerHTML = '';
    
    trade.steps.forEach(step => {
        const div = document.createElement('div');
        div.className = 'tl-item';
        div.innerHTML = `
            <div class="tl-dot"></div>
            <div class="tl-time">${new Date(step.timestamp).toLocaleString()} | Price: ${step.price_level.toFixed(5)}</div>
            <div class="tl-title">${step.step_name} <span class="badge" style="margin-top:0">${step.timeframe}</span></div>
            <div class="tl-desc">${step.description}</div>
        `;
        tl.appendChild(div);
    });
    
    document.getElementById('inspector-modal').classList.add('active');
}

// Metrics Dashboard JavaScript
const API_ROOT = '/api/v1';

// Password protection
const METRICS_STORAGE_KEY = 'vncrcc.metrics_auth';

// Check if already authenticated
function isAuthenticated() {
  const stored = localStorage.getItem(METRICS_STORAGE_KEY);
  if (!stored) return false;
  try {
    const data = JSON.parse(stored);
    // Auth expires after 24 hours
    return data.timestamp && (Date.now() - data.timestamp < 24 * 60 * 60 * 1000);
  } catch {
    return false;
  }
}

// Prompt for password
async function authenticate() {
  return new Promise((resolve) => {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay show';
    overlay.innerHTML = `
      <div class="modal" role="dialog" aria-modal="true">
        <header>
          <h3>Metrics Access</h3>
        </header>
        <div class="modal-body">
          <p style="color:#9fb9d8;margin-bottom:12px;">Enter admin password to view metrics dashboard.</p>
          <div style="position:relative;">
            <input type="password" id="metrics-password" placeholder="Password" 
                   style="width:100%;padding:8px;background:#0f1928;border:1px solid #4a90e2;color:#dfefff;border-radius:4px;font-size:14px;" />
            <button id="metrics-toggle-pwd" style="position:absolute;right:8px;top:50%;transform:translateY(-50%);background:none;border:none;color:#9fb9d8;cursor:pointer;font-size:18px;" title="Show password">👁</button>
          </div>
        </div>
        <footer>
          <button class="btn" id="metrics-cancel">Cancel</button>
          <button class="btn" id="metrics-submit">Access</button>
        </footer>
      </div>`;
    document.body.appendChild(overlay);
    
    const input = overlay.querySelector('#metrics-password');
    const submit = overlay.querySelector('#metrics-submit');
    const cancel = overlay.querySelector('#metrics-cancel');
    const togglePwd = overlay.querySelector('#metrics-toggle-pwd');
    
    // Toggle password visibility
    let showPassword = false;
    togglePwd.addEventListener('mousedown', () => {
      showPassword = true;
      input.type = 'text';
    });
    togglePwd.addEventListener('mouseup', () => {
      showPassword = false;
      input.type = 'password';
    });
    togglePwd.addEventListener('mouseleave', () => {
      if (showPassword) {
        showPassword = false;
        input.type = 'password';
      }
    });
    
    cancel.addEventListener('click', () => {
      overlay.remove();
      resolve(false);
    });
    
    const handleSubmit = async () => {
      const password = input.value.trim();
      if (!password) return;
      
      // Verify password by attempting to access a protected endpoint
      try {
        const resp = await fetch(`${API_ROOT}/p56/purge`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ password, keys: [] })
        });
        
        if (resp.ok || resp.status === 400) { // 400 = valid password but empty keys
          localStorage.setItem(METRICS_STORAGE_KEY, JSON.stringify({ timestamp: Date.now() }));
          overlay.remove();
          resolve(true);
        } else {
          input.style.borderColor = '#f87171';
          input.value = '';
          input.placeholder = 'Invalid password';
          setTimeout(() => {
            input.style.borderColor = '#4a90e2';
            input.placeholder = 'Password';
          }, 2000);
        }
      } catch (err) {
        console.error('Auth error', err);
        overlay.remove();
        resolve(false);
      }
    };
    
    submit.addEventListener('click', handleSubmit);
    input.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') handleSubmit();
    });
    
    input.focus();
  });
}

// Initialize charts
let usersChart, requestsChart, resourcesChart, delayChart, errorChart;

// Historical data for line charts
const historyLimit = 60; // Keep last 60 data points
const usersHistory = [];
const requestsHistory = [];
const cpuHistory = [];
const memoryHistory = [];
const delayHistory = [];
const errorHistory = [];
const timeLabels = [];

function initCharts() {
  const chartDefaults = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: true, labels: { color: '#9fb9d8' } }
    },
    scales: {
      x: { ticks: { color: '#9fb9d8' }, grid: { color: 'rgba(74, 144, 226, 0.1)' } },
      y: { ticks: { color: '#9fb9d8' }, grid: { color: 'rgba(74, 144, 226, 0.1)' } }
    }
  };

  // Active Users Chart
  usersChart = new Chart(document.getElementById('users-chart'), {
    type: 'line',
    data: {
      labels: timeLabels,
      datasets: [{
        label: 'Active Users',
        data: usersHistory,
        borderColor: '#4ade80',
        backgroundColor: 'rgba(74, 222, 128, 0.1)',
        tension: 0.4,
        fill: true
      }]
    },
    options: { ...chartDefaults }
  });

  // Request Rate Chart
  requestsChart = new Chart(document.getElementById('requests-chart'), {
    type: 'line',
    data: {
      labels: timeLabels,
      datasets: [{
        label: 'Req/s (1min avg)',
        data: requestsHistory,
        borderColor: '#4a90e2',
        backgroundColor: 'rgba(74, 144, 226, 0.1)',
        tension: 0.4,
        fill: true
      }]
    },
    options: { ...chartDefaults }
  });

  // Resource Usage Chart (CPU + Memory)
  resourcesChart = new Chart(document.getElementById('resources-chart'), {
    type: 'line',
    data: {
      labels: timeLabels,
      datasets: [
        {
          label: 'CPU %',
          data: cpuHistory,
          borderColor: '#fbbf24',
          backgroundColor: 'rgba(251, 191, 36, 0.1)',
          tension: 0.4,
          yAxisID: 'y'
        },
        {
          label: 'Memory %',
          data: memoryHistory,
          borderColor: '#f87171',
          backgroundColor: 'rgba(248, 113, 113, 0.1)',
          tension: 0.4,
          yAxisID: 'y'
        }
      ]
    },
    options: {
      ...chartDefaults,
      scales: {
        ...chartDefaults.scales,
        y: { 
          ...chartDefaults.scales.y,
          min: 0,
          max: 100
        }
      }
    }
  });

  // VATSIM Delay Chart
  delayChart = new Chart(document.getElementById('delay-chart'), {
    type: 'line',
    data: {
      labels: timeLabels,
      datasets: [{
        label: 'Data Age (seconds)',
        data: delayHistory,
        borderColor: '#f87171',
        backgroundColor: 'rgba(248, 113, 113, 0.1)',
        tension: 0.4,
        fill: true
      }]
    },
    options: { ...chartDefaults }
  });

  // Error Rate Chart
  errorChart = new Chart(document.getElementById('error-chart'), {
    type: 'line',
    data: {
      labels: timeLabels,
      datasets: [{
        label: 'Errors/min',
        data: errorHistory,
        borderColor: '#fb923c',
        backgroundColor: 'rgba(251, 146, 60, 0.1)',
        tension: 0.4,
        fill: true
      }]
    },
    options: { ...chartDefaults }
  });
}

// Fetch and update metrics
async function updateMetrics() {
  try {
    const resp = await fetch('/api/metrics');
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    
    const data = await resp.json();
    
    // Update timestamp
    document.getElementById('last-update').textContent = new Date().toLocaleTimeString();
    
    // Update summary cards
    document.getElementById('active-users').textContent = data.active_users || 0;
    document.getElementById('request-rate').textContent = (data.request_rate['1min'] || 0).toFixed(2);
    
    const cpuPct = data.resources?.cpu_percent || 0;
    const cpuElem = document.getElementById('cpu-usage');
    cpuElem.textContent = `${cpuPct.toFixed(1)}%`;
    cpuElem.className = 'metric-value ' + (cpuPct > 80 ? 'status-danger' : cpuPct > 50 ? 'status-warning' : 'status-good');
    
    const memUsed = data.resources?.memory?.used_mb || 0;
    const memPct = data.resources?.memory?.percent || 0;
    const memElem = document.getElementById('memory-usage');
    memElem.textContent = `${memUsed.toFixed(0)}`;
    memElem.className = 'metric-value ' + (memPct > 90 ? 'status-danger' : memPct > 70 ? 'status-warning' : 'status-good');
    
    const uptimeHours = (data.uptime_seconds / 3600).toFixed(1);
    document.getElementById('uptime').textContent = uptimeHours;
    
    const errorRate = ((data.error_rate['1min'] || 0) * 60).toFixed(1); // errors per minute
    const errElem = document.getElementById('error-rate');
    errElem.textContent = errorRate;
    errElem.className = 'metric-value ' + (errorRate > 10 ? 'status-danger' : errorRate > 1 ? 'status-warning' : 'status-good');
    
    // Disk usage
    const diskElem = document.getElementById('disk-usage');
    if (data.resources?.error || !data.resources?.disk) {
      diskElem.textContent = 'N/A';
      diskElem.className = 'metric-value';
    } else {
      const diskFree = data.resources.disk.free_gb || 0;
      const diskPct = data.resources.disk.percent || 0;
      diskElem.textContent = diskFree.toFixed(1);
      diskElem.className = 'metric-value ' + (diskPct > 90 ? 'status-danger' : diskPct > 80 ? 'status-warning' : 'status-good');
    }

    // VATSIM Data Age
    const delayData = data.delay?.['1min'] || {};
    const currentDelay = delayData.current || 0;
    const delayElem = document.getElementById('vatsim-delay');
    delayElem.textContent = currentDelay.toFixed(1);
    delayElem.className = 'metric-value ' + (currentDelay > 45 ? 'status-danger' : currentDelay > 30 ? 'status-warning' : 'status-good');

    // Update history
    const now = new Date();
    const timeLabel = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });

    timeLabels.push(timeLabel);
    usersHistory.push(data.active_users || 0);
    requestsHistory.push(data.request_rate['1min'] || 0);
    cpuHistory.push(cpuPct);
    memoryHistory.push(memPct);
    delayHistory.push(currentDelay);
    errorHistory.push(parseFloat(errorRate));

    // Keep only last N points
    if (timeLabels.length > historyLimit) {
      timeLabels.shift();
      usersHistory.shift();
      requestsHistory.shift();
      cpuHistory.shift();
      memoryHistory.shift();
      delayHistory.shift();
      errorHistory.shift();
    }

    // Update line charts
    usersChart.update('none');
    requestsChart.update('none');
    resourcesChart.update('none');
    delayChart.update('none');
    errorChart.update('none');

    // Update endpoints table
    const endpoints = data.endpoints || {};
    const tbody = document.getElementById('endpoints-tbody');
    tbody.innerHTML = '';
    Object.entries(endpoints)
      .sort((a, b) => b[1].requests_5min - a[1].requests_5min)
      .forEach(([path, stats]) => {
        const row = document.createElement('tr');
        row.innerHTML = `
          <td><code>${path}</code></td>
          <td>${stats.requests_1min}</td>
          <td>${stats.requests_5min}</td>
          <td class="${stats.errors_1min > 0 ? 'status-danger' : ''}">${stats.errors_1min}</td>
        `;
        tbody.appendChild(row);
      });
    
    // Update P56 purge history table
    const purges = data.p56_purges || [];
    const purgesTbody = document.getElementById('purges-tbody');
    const noPurges = document.getElementById('no-purges');
    
    if (purges.length === 0) {
      purgesTbody.innerHTML = '';
      noPurges.style.display = 'block';
    } else {
      noPurges.style.display = 'none';
      purgesTbody.innerHTML = '';
      purges.forEach(purge => {
        const row = document.createElement('tr');
        row.innerHTML = `
          <td>${purge.timestamp}</td>
          <td>${purge.count}</td>
          <td><code>${purge.ip}</code></td>
        `;
        purgesTbody.appendChild(row);
      });
    }
    
  } catch (err) {
    console.error('Failed to fetch metrics', err);
    document.getElementById('last-update').textContent = 'Error loading metrics';
  }
}

// Initialize
(async function init() {
  // Check authentication
  if (!isAuthenticated()) {
    const authed = await authenticate();
    if (!authed) {
      window.location.href = '/';
      return;
    }
  }
  
  // Initialize charts
  initCharts();
  
  // Initial load
  await updateMetrics();
  
  // Auto-refresh every 15 seconds (reduce load)
  setInterval(updateMetrics, 15000);
})();

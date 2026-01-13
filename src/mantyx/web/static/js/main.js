// Mantyx Frontend JavaScript

// API Base URL
const API_BASE = '/api';

// State
let apps = [];
let currentAppId = null;

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    initializeEventListeners();
    loadApps();
    
    // Auto-refresh every 5 seconds
    setInterval(loadApps, 5000);
});

// Event Listeners
function initializeEventListeners() {
    // Upload button
    document.getElementById('uploadBtn').addEventListener('click', () => {
        openModal('uploadModal');
    });
    
    // Refresh button
    document.getElementById('refreshBtn').addEventListener('click', () => {
        loadApps();
    });
    
    // Modal close buttons
    document.querySelectorAll('.modal .close').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const modal = e.target.closest('.modal');
            closeModal(modal.id);
        });
    });
    
    // Click outside modal to close
    document.querySelectorAll('.modal').forEach(modal => {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                closeModal(modal.id);
            }
        });
    });
    
    // Tab switching
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const tabName = e.target.dataset.tab;
            switchTab(tabName);
        });
    });
    
    // Forms
    document.getElementById('zipUploadForm').addEventListener('submit', handleZipUpload);
    document.getElementById('gitUploadForm').addEventListener('submit', handleGitUpload);
}

// Modal Management
function openModal(modalId) {
    const modal = document.getElementById(modalId);
    modal.classList.add('active');
}

function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    modal.classList.remove('active');
}

function switchTab(tabName) {
    // Update tab buttons
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tabName);
    });
    
    // Update tab content
    document.querySelectorAll('.tab-content').forEach(content => {
        const contentTab = content.id.replace('Tab', '');
        content.classList.toggle('active', contentTab === tabName);
    });
}

// API Calls
async function apiCall(endpoint, options = {}) {
    try {
        const response = await fetch(`${API_BASE}${endpoint}`, {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers,
            },
            ...options,
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'API request failed');
        }
        
        return await response.json();
    } catch (error) {
        console.error('API Error:', error);
        alert(`Error: ${error.message}`);
        throw error;
    }
}

// Load Apps
async function loadApps() {
    try {
        apps = await apiCall('/apps');
        renderApps();
        updateStats();
    } catch (error) {
        console.error('Failed to load apps:', error);
    }
}

// Render Apps
function renderApps() {
    const container = document.getElementById('appsList');
    
    if (apps.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <h3>No applications yet</h3>
                <p>Click "Upload App" to get started</p>
            </div>
        `;
        return;
    }
    
    container.innerHTML = apps.map(app => `
        <div class="app-card" onclick="showAppDetails(${app.id})">
            <div class="app-header">
                <div>
                    <div class="app-title">${app.display_name}</div>
                    <div class="app-name">${app.name}</div>
                </div>
                <span class="status-badge ${app.state}">${app.state}</span>
            </div>
            
            ${app.description ? `<div class="app-description">${app.description}</div>` : ''}
            
            <div class="app-meta">
                <div class="meta-item">
                    <span>📦</span>
                    <span>${app.app_type}</span>
                </div>
                <div class="meta-item">
                    <span>🔢</span>
                    <span>v${app.version}</span>
                </div>
                ${app.pid ? `
                <div class="meta-item">
                    <span>🔧</span>
                    <span>PID: ${app.pid}</span>
                </div>
                ` : ''}
                ${app.web_url ? `
                <div class="meta-item">
                    <span>🌐</span>
                    <a href="${app.web_url}" target="_blank" onclick="event.stopPropagation()">Open</a>
                </div>
                ` : ''}
            </div>
            
            <div class="app-actions" onclick="event.stopPropagation()">
                ${getAppActions(app)}
            </div>
        </div>
    `).join('');
}

// Get App Actions
function getAppActions(app) {
    let actions = [];
    
    // State-specific actions
    if (app.state === 'uploaded') {
        actions.push(`<button class="btn btn-success btn-small" onclick="installApp(${app.id})">Install</button>`);
    }
    
    if (app.state === 'installed' || app.state === 'disabled') {
        actions.push(`<button class="btn btn-success btn-small" onclick="enableApp(${app.id})">Enable</button>`);
    }
    
    if (app.state === 'enabled' || app.state === 'running' || app.state === 'stopped') {
        actions.push(`<button class="btn btn-warning btn-small" onclick="disableApp(${app.id})">Disable</button>`);
    }
    
    // Perpetual app controls
    if (app.app_type === 'perpetual') {
        if (app.state === 'running') {
            actions.push(`<button class="btn btn-warning btn-small" onclick="stopApp(${app.id})">Stop</button>`);
            actions.push(`<button class="btn btn-secondary btn-small" onclick="restartApp(${app.id})">Restart</button>`);
        } else if (app.state === 'enabled' || app.state === 'stopped' || app.state === 'failed') {
            actions.push(`<button class="btn btn-success btn-small" onclick="startApp(${app.id})">Start</button>`);
        }
    }
    
    // Delete
    actions.push(`<button class="btn btn-danger btn-small" onclick="deleteApp(${app.id})">Delete</button>`);
    
    return actions.join('');
}

// Update Stats
function updateStats() {
    const total = apps.length;
    const running = apps.filter(a => a.state === 'running').length;
    const enabled = apps.filter(a => a.state === 'enabled' || a.state === 'running').length;
    const failed = apps.filter(a => a.state === 'failed').length;
    
    document.getElementById('totalApps').textContent = total;
    document.getElementById('runningApps').textContent = running;
    document.getElementById('enabledApps').textContent = enabled;
    document.getElementById('failedApps').textContent = failed;
}

// App Actions
async function installApp(appId) {
    if (confirm('Install dependencies for this app?')) {
        try {
            await apiCall(`/apps/${appId}/install`, { method: 'POST' });
            alert('App installed successfully');
            loadApps();
        } catch (error) {
            // Error already handled in apiCall
        }
    }
}

async function enableApp(appId) {
    try {
        await apiCall(`/apps/${appId}/enable`, { method: 'POST' });
        loadApps();
    } catch (error) {
        // Error already handled
    }
}

async function disableApp(appId) {
    try {
        await apiCall(`/apps/${appId}/disable`, { method: 'POST' });
        loadApps();
    } catch (error) {
        // Error already handled
    }
}

async function startApp(appId) {
    try {
        await apiCall(`/apps/${appId}/start`, { method: 'POST' });
        loadApps();
    } catch (error) {
        // Error already handled
    }
}

async function stopApp(appId) {
    if (confirm('Stop this app?')) {
        try {
            await apiCall(`/apps/${appId}/stop`, { method: 'POST' });
            loadApps();
        } catch (error) {
            // Error already handled
        }
    }
}

async function restartApp(appId) {
    if (confirm('Restart this app?')) {
        try {
            await apiCall(`/apps/${appId}/restart`, { method: 'POST' });
            loadApps();
        } catch (error) {
            // Error already handled
        }
    }
}

async function deleteApp(appId) {
    if (confirm('Are you sure you want to delete this app? This action cannot be undone.')) {
        try {
            await apiCall(`/apps/${appId}`, { method: 'DELETE' });
            alert('App deleted successfully');
            loadApps();
        } catch (error) {
            // Error already handled
        }
    }
}

// Upload Handlers
async function handleZipUpload(e) {
    e.preventDefault();
    
    const formData = new FormData(e.target);
    
    try {
        const response = await fetch(`${API_BASE}/apps/upload/zip`, {
            method: 'POST',
            body: formData,
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Upload failed');
        }
        
        const result = await response.json();
        alert(`App uploaded successfully! Install it to continue.`);
        closeModal('uploadModal');
        e.target.reset();
        loadApps();
    } catch (error) {
        alert(`Upload failed: ${error.message}`);
    }
}

async function handleGitUpload(e) {
    e.preventDefault();
    
    const formData = new FormData(e.target);
    
    try {
        const response = await fetch(`${API_BASE}/apps/upload/git`, {
            method: 'POST',
            body: formData,
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Upload failed');
        }
        
        const result = await response.json();
        alert(`App created from Git successfully! Install it to continue.`);
        closeModal('uploadModal');
        e.target.reset();
        loadApps();
    } catch (error) {
        alert(`Upload failed: ${error.message}`);
    }
}

// App Details
async function showAppDetails(appId) {
    currentAppId = appId;
    const app = apps.find(a => a.id === appId);
    
    if (!app) return;
    
    // Load executions
    let executions = [];
    try {
        executions = await apiCall(`/executions?app_id=${appId}&limit=10`);
    } catch (error) {
        console.error('Failed to load executions:', error);
    }
    
    // Load schedules
    let schedules = [];
    try {
        schedules = await apiCall(`/schedules?app_id=${appId}`);
    } catch (error) {
        console.error('Failed to load schedules:', error);
    }
    
    const content = document.getElementById('appDetailsContent');
    content.innerHTML = `
        <h2>${app.display_name}</h2>
        <p class="app-name">${app.name}</p>
        
        <div style="margin: 1.5rem 0;">
            <h3>Status</h3>
            <p><strong>State:</strong> <span class="status-badge ${app.state}">${app.state}</span></p>
            <p><strong>Type:</strong> ${app.app_type}</p>
            <p><strong>Version:</strong> ${app.version}</p>
            ${app.pid ? `<p><strong>PID:</strong> ${app.pid}</p>` : ''}
            ${app.restart_count > 0 ? `<p><strong>Restart Count:</strong> ${app.restart_count}</p>` : ''}
        </div>
        
        ${app.description ? `
        <div style="margin: 1.5rem 0;">
            <h3>Description</h3>
            <p>${app.description}</p>
        </div>
        ` : ''}
        
        <div style="margin: 1.5rem 0;">
            <h3>Configuration</h3>
            <p><strong>Entrypoint:</strong> <code>${app.entrypoint}</code></p>
            <p><strong>Restart Policy:</strong> ${app.restart_policy}</p>
            ${app.git_url ? `<p><strong>Git URL:</strong> ${app.git_url}</p>` : ''}
            ${app.git_branch ? `<p><strong>Git Branch:</strong> ${app.git_branch}</p>` : ''}
        </div>
        
        ${executions.length > 0 ? `
        <div style="margin: 1.5rem 0;">
            <h3>Recent Executions</h3>
            <div style="max-height: 300px; overflow-y: auto;">
                ${executions.map(exec => `
                    <div style="background: var(--bg-tertiary); padding: 0.8rem; margin: 0.5rem 0; border-radius: 4px;">
                        <div><strong>ID:</strong> ${exec.id} | <strong>Status:</strong> ${exec.status}</div>
                        ${exec.started_at ? `<div><strong>Started:</strong> ${new Date(exec.started_at).toLocaleString()}</div>` : ''}
                        ${exec.exit_code !== null ? `<div><strong>Exit Code:</strong> ${exec.exit_code}</div>` : ''}
                    </div>
                `).join('')}
            </div>
        </div>
        ` : ''}
        
        ${schedules.length > 0 ? `
        <div style="margin: 1.5rem 0;">
            <h3>Schedules</h3>
            ${schedules.map(sched => `
                <div style="background: var(--bg-tertiary); padding: 0.8rem; margin: 0.5rem 0; border-radius: 4px;">
                    <div><strong>${sched.name}</strong> - ${sched.schedule_type}</div>
                    <div>${sched.cron_expression || `Every ${sched.interval_seconds}s`}</div>
                    <div>Run count: ${sched.run_count}</div>
                </div>
            `).join('')}
        </div>
        ` : ''}
    `;
    
    openModal('appDetailsModal');
}

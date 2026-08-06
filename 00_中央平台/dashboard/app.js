// AI Hub Management Console JavaScript

document.addEventListener('DOMContentLoaded', () => {
    // State
    const state = {
        currentTab: 'nav',
        gateways: {},
        stats: {},
        repos: [],
        syncLogs: []
    };

    // DOM Elements
    const navItems = document.querySelectorAll('.nav-item');
    const tabPages = document.querySelectorAll('.tab-page');
    const pageTitle = document.getElementById('page-title');
    const pageSubtitle = document.getElementById('page-subtitle');
    const refreshBtn = document.getElementById('refresh-btn');

    // Modals
    const registerModal = document.getElementById('register-modal');
    const openRegisterModalBtn = document.getElementById('open-register-modal-btn');
    const closeRegisterModalBtn = document.getElementById('close-register-modal');
    const cancelRegisterModalBtn = document.getElementById('cancel-register-modal');
    const registerGatewayForm = document.getElementById('register-gateway-form');

    const githubModal = document.getElementById('github-modal');
    const openGithubModalBtn = document.getElementById('open-github-modal-btn');
    const closeGithubModalBtn = document.getElementById('close-github-modal');
    const cancelGithubModalBtn = document.getElementById('cancel-github-modal');
    const createGithubForm = document.getElementById('create-github-form');

    const triggerSyncBtn = document.getElementById('trigger-sync-btn');
    const feishuLogBox = document.getElementById('feishu-log-box');

    // Tab Subtitles Map
    const tabSubtitles = {
        nav: { title: '导航首页', subtitle: '中央 AI 服务中转与网关路由中心' },
        gateways: { title: '网关管理', subtitle: '集中配置、心跳监控与节点运维' },
        github: { title: 'GitHub 项目', subtitle: '团队代码仓库同步与 Issue 跟踪' },
        feishu: { title: '飞书同步', subtitle: '多维表格 JSON 增量同步中心' },
        stats: { title: '统计分析', subtitle: '全域调用量与健康度多维分析' }
    };

    // ---------------------------------------------------- Navigation & Tab Switching
    navItems.forEach(item => {
        item.addEventListener('click', () => {
            const tab = item.getAttribute('data-tab');
            switchTab(tab);
        });
    });

    function switchTab(tab) {
        state.currentTab = tab;
        navItems.forEach(item => {
            if (item.getAttribute('data-tab') === tab) {
                item.classList.add('active');
            } else {
                item.classList.remove('active');
            }
        });

        tabPages.forEach(page => {
            if (page.id === `tab-${tab}`) {
                page.classList.add('active');
            } else {
                page.classList.remove('active');
            }
        });

        if (tabSubtitles[tab]) {
            pageTitle.innerText = tabSubtitles[tab].title;
            pageSubtitle.innerText = tabSubtitles[tab].subtitle;
        }

        // Trigger view-specific data refresh
        if (tab === 'github') fetchGitHubRepos();
        if (tab === 'stats') fetchStats();
    }

    // ---------------------------------------------------- Toasts
    function showToast(message, type = 'success') {
        const container = document.getElementById('toast-container');
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.innerText = message;
        container.appendChild(toast);
        setTimeout(() => {
            toast.style.opacity = '0';
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }

    // ---------------------------------------------------- Fetch Data Functions

    async function fetchGateways() {
        try {
            const res = await fetch('/api/gateways');
            if (!res.ok) throw new Error('网络响应异常');
            const data = await res.json();
            state.gateways = data.gateways || {};
            renderGateways();
        } catch (err) {
            console.error('获取网关数据失败:', err);
        }
    }

    async function fetchStats() {
        try {
            const res = await fetch('/api/stats');
            if (res.ok) {
                state.stats = await res.json();
                renderStats();
            }
        } catch (err) {
            console.error('获取统计失败:', err);
        }
    }

    async function fetchGitHubRepos() {
        try {
            const res = await fetch('/api/github/repos');
            const data = await res.json();
            if (data.repos) {
                state.repos = data.repos;
                renderRepos(state.repos);
            } else if (data.error) {
                renderReposError(data.error);
            }
        } catch (err) {
            renderReposError('无法获取 GitHub 仓库信息');
        }
    }

    // ---------------------------------------------------- Render Functions

    function renderGateways() {
        const entries = Object.entries(state.gateways);
        const grid = document.getElementById('gateway-cards-grid');
        const tableBody = document.getElementById('gateways-table-body');
        
        let onlineCount = 0;
        let offlineCount = 0;

        // Banner stats
        entries.forEach(([id, gw]) => {
            if (gw.status === 'online') onlineCount++;
            else offlineCount++;
        });

        document.getElementById('nav-total-gw').innerText = entries.length;
        document.getElementById('nav-online-gw').innerText = onlineCount;
        document.getElementById('nav-offline-gw').innerText = offlineCount;

        // Render Cards Grid
        if (entries.length === 0) {
            grid.innerHTML = '<p class="text-muted" style="grid-column: 1/-1; text-align: center; padding: 40px;">暂无已注册的网关</p>';
        } else {
            grid.innerHTML = entries.map(([id, gw]) => {
                const isOnline = gw.status === 'online';
                const statusClass = isOnline ? 'online' : 'offline';
                const statusText = isOnline ? '在线' : '离线';
                return `
                <div class="gateway-card ${statusClass}" onclick="window.open('${gw.url}', '_blank')">
                    <div class="gw-header">
                        <span class="gw-icon">${gw.icon || '🔗'}</span>
                        <span class="badge ${statusClass}">${statusText}</span>
                    </div>
                    <div class="gw-name">${gw.name || id}</div>
                    <div class="gw-desc">${gw.description || '暂无描述信息'}</div>
                    <div class="gw-footer">
                        <span>端口 ${gw.port}</span>
                        <span>最后在线: ${(gw.last_seen || '').slice(11, 19) || '未知'}</span>
                    </div>
                </div>`;
            }).join('');
        }

        // Render Table
        if (entries.length === 0) {
            tableBody.innerHTML = '<tr><td colspan="6" style="text-align:center; color:#888;">暂无数据</td></tr>';
        } else {
            tableBody.innerHTML = entries.map(([id, gw]) => {
                const isOnline = gw.status === 'online';
                const statusBadge = isOnline ? '<span class="badge online">在线</span>' : '<span class="badge offline">离线</span>';
                return `
                <tr>
                    <td><strong>${gw.name || id}</strong></td>
                    <td><code>${gw.port}</code></td>
                    <td><a href="${gw.url}" target="_blank" style="color:var(--primary);">${gw.url}</a></td>
                    <td>${statusBadge}</td>
                    <td>${gw.last_seen || '-'}</td>
                    <td>
                        <button class="btn btn-sm btn-secondary" onclick="checkHealth('${id}')">健康检查</button>
                        <button class="btn btn-sm btn-danger" onclick="unregisterGateway('${id}')">注销</button>
                    </td>
                </tr>`;
            }).join('');
        }
    }

    function renderRepos(repos) {
        const grid = document.getElementById('github-repos-grid');
        if (!repos || repos.length === 0) {
            grid.innerHTML = '<p class="text-muted" style="grid-column: 1/-1; text-align: center; padding: 40px;">未匹配到仓库记录</p>';
            return;
        }

        grid.innerHTML = repos.map(repo => `
            <div class="repo-card">
                <div>
                    <a href="${repo.url}" target="_blank" class="repo-title">📦 ${repo.name}</a>
                    <p class="repo-desc">${repo.description || '暂无描述'}</p>
                </div>
                <div class="repo-meta">
                    <span>🏷️ ${repo.language || '未知'}</span>
                    <span>🕒 ${(repo.updated_at || '').slice(0, 10)}</span>
                </div>
            </div>
        `).join('');
    }

    function renderReposError(errMsg) {
        const grid = document.getElementById('github-repos-grid');
        grid.innerHTML = `<div style="grid-column: 1/-1; background:var(--bg-card); padding:30px; border-radius:12px; text-align:center; color:var(--text-muted);">
            ⚠️ ${errMsg}
            <br><small style="color:var(--text-dim); margin-top:8px; display:inline-block;">请在环境变量中配置 GITHUB_TOKEN 以启用 GitHub 项目同步功能</small>
        </div>`;
    }

    function renderStats() {
        const container = document.getElementById('stats-gw-progress');
        const gateways = state.gateways || {};
        const total = Object.keys(gateways).length || 1;
        
        let online = 0;
        Object.values(gateways).forEach(g => { if (g.status === 'online') online++; });
        
        const onlinePct = Math.round((online / total) * 100);

        container.innerHTML = `
            <div style="margin-bottom:14px;">
                <div style="display:flex; justify-content:space-between; font-size:13px; margin-bottom:6px;">
                    <span>在线在线率</span>
                    <strong>${onlinePct}% (${online}/${total})</strong>
                </div>
                <div style="height:10px; background:#1a1c2b; border-radius:5px; overflow:hidden;">
                    <div style="width:${onlinePct}%; height:100%; background:var(--emerald);"></div>
                </div>
            </div>
        `;
    }

    // ---------------------------------------------------- Actions (Global functions)

    window.checkHealth = async function(id) {
        showToast(`正在检查 ${id} 健康状态...`, 'success');
        try {
            const res = await fetch(`/api/gateways/${id}/health`);
            const data = await res.json();
            if (data.status === 'online') {
                showToast(`网关 ${id} 运行正常 (HTTP 200)`, 'success');
            } else {
                showToast(`网关 ${id} 异常: ${data.error || '无法访问'}`, 'error');
            }
            fetchGateways();
        } catch (err) {
            showToast(`请求超时`, 'error');
        }
    };

    window.unregisterGateway = async function(id) {
        if (!confirm(`确定要注销网关 [${id}] 吗？`)) return;
        try {
            const res = await fetch(`/api/gateways/${id}/unregister`, { method: 'POST' });
            if (res.ok) {
                showToast(`网关 ${id} 已成功注销`, 'success');
                fetchGateways();
            }
        } catch (err) {
            showToast(`注销失败`, 'error');
        }
    };

    // ---------------------------------------------------- Modal & Form Handling

    openRegisterModalBtn.onclick = () => registerModal.classList.add('active');
    closeRegisterModalBtn.onclick = () => registerModal.classList.remove('active');
    cancelRegisterModalBtn.onclick = () => registerModal.classList.remove('active');

    openGithubModalBtn.onclick = () => githubModal.classList.add('active');
    closeGithubModalBtn.onclick = () => githubModal.classList.remove('active');
    cancelGithubModalBtn.onclick = () => githubModal.classList.remove('active');

    registerGatewayForm.onsubmit = async (e) => {
        e.preventDefault();
        const formData = new FormData(registerGatewayForm);
        const payload = {
            name: formData.get('name'),
            icon: formData.get('icon') || '🔗',
            description: formData.get('description') || '',
            port: parseInt(formData.get('port'), 10) || 3001
        };

        try {
            const res = await fetch('/api/gateways', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (res.ok) {
                showToast(`网关 ${payload.name} 注册成功!`, 'success');
                registerModal.classList.remove('active');
                registerGatewayForm.reset();
                fetchGateways();
            } else {
                showToast('注册失败', 'error');
            }
        } catch (err) {
            showToast('请求失败', 'error');
        }
    };

    createGithubForm.onsubmit = async (e) => {
        e.preventDefault();
        showToast('创建仓库接口调用成功 (开发模式模拟)', 'success');
        githubModal.classList.remove('active');
        createGithubForm.reset();
    };

    triggerSyncBtn.onclick = async () => {
        showToast('正在触发飞书多维表格增量同步...', 'success');
        const now = new Date().toLocaleTimeString();
        try {
            const res = await fetch('/api/feishu/sync', { method: 'POST' });
            const data = await res.json();
            const logLine = document.createElement('div');
            logLine.className = 'log-line success';
            logLine.innerText = `[${now}] [SYNC OK] ${data.message || '数据已同步到飞书多维表格'}`;
            feishuLogBox.appendChild(logLine);
            feishuLogBox.scrollTop = feishuLogBox.scrollHeight;
        } catch (err) {
            const logLine = document.createElement('div');
            logLine.className = 'log-line error';
            logLine.innerText = `[${now}] [SYNC FAIL] 传输失败: ${err.message}`;
            feishuLogBox.appendChild(logLine);
        }
    };

    refreshBtn.onclick = () => {
        showToast('正在刷新...', 'success');
        fetchGateways();
        fetchStats();
        if (state.currentTab === 'github') fetchGitHubRepos();
    };

    // GitHub Search Filter
    const githubSearchInput = document.getElementById('github-search-input');
    githubSearchInput.oninput = (e) => {
        const query = e.target.value.toLowerCase();
        const filtered = state.repos.filter(r => 
            (r.name || '').toLowerCase().includes(query) || 
            (r.description || '').toLowerCase().includes(query)
        );
        renderRepos(filtered);
    };

    // Initial Load & Interval Polling
    fetchGateways();
    fetchStats();
    setInterval(fetchGateways, 10000);
});

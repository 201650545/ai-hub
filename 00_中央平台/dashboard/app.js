// AI Hub Management Console JavaScript

document.addEventListener('DOMContentLoaded', () => {
    // State
    const state = {
        currentTab: 'nav',
        gateways: {},
        stats: {},
        repos: [],
        syncLogs: [],
        resources: null
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
        stats: { title: '统计分析', subtitle: '全域调用量与健康度多维分析' },
        resources: { title: '资源清单', subtitle: 'ai-resource-hub 公开数据桥 · 能力与实例清单（飞书表 → GitHub Pages → 门户）' }
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
        if (tab === 'resources') fetchResources();
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

    async function editRepoDescription(repoName, currentDesc) {
        const newDesc = prompt(`修改「${repoName}」的项目描述：`, currentDesc || '');
        if (newDesc === null) return;
        try {
            const res = await fetch('/api/github/repos/update_description', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: repoName, description: newDesc.trim() })
            });
            const data = await res.json();
            if (data.ok) {
                const target = state.repos.find(r => r.name === repoName);
                if (target) target.description = newDesc.trim() || '暂无描述';
                renderRepos(state.repos);
                showToast(`✅ 已更新 ${repoName} 描述`, 'success');
            } else {
                showToast(`更新失败: ${data.error || '未知错误'}`, 'danger');
            }
        } catch (err) {
            showToast(`请求失败: ${err.message}`, 'danger');
        }
    }
    window.editRepoDescription = editRepoDescription;

    function renderRepos(repos) {
        const grid = document.getElementById('github-repos-grid');
        if (!repos || repos.length === 0) {
            grid.innerHTML = '<p class="text-muted" style="grid-column: 1/-1; text-align: center; padding: 40px;">未匹配到仓库记录</p>';
            return;
        }

        grid.innerHTML = repos.map(repo => {
            let desc = repo.description || '暂无描述';
            if (desc.includes('??')) {
                desc = desc.replace(/\?\?/g, '').trim() || '个人 AI 中转网关 (Multi-Gateway AI Hub)';
            }
            const cleanDesc = desc.replace(/'/g, "\\'").replace(/"/g, '&quot;');
            return `
            <div class="repo-card">
                <div>
                    <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:8px;">
                        <a href="${repo.url || '#'}" target="_blank" class="repo-title" style="flex:1; word-break:break-all;">📦 ${repo.name}</a>
                        <button class="btn btn-sm btn-secondary" onclick="window.editRepoDescription('${repo.name}', '${cleanDesc}')" style="font-size:11px; padding:3px 8px; white-space:nowrap; border-radius:6px; cursor:pointer;">✏️ 修改描述</button>
                    </div>
                    <p class="repo-desc" style="margin-top:8px;">${desc}</p>
                </div>
                <div class="repo-meta">
                    <span>🏷️ ${repo.language || 'Python'}</span>
                    <span>🕒 ${(repo.updated_at || '').slice(0, 10) || '2026-08-07'}</span>
                </div>
            </div>`;
        }).join('');
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

    // ---------------------------------------------------- 资源清单（ai-resource-hub 数据桥）
    // P0 加固：全部走 DOM 节点 + textContent 构建，杜绝上游文本被当 HTML 解析（XSS/DOM 注入面）
    function makeBadge(text, cls) {
        const span = document.createElement('span');
        span.className = 'badge ' + cls;
        span.textContent = text;
        return span;
    }
    function quotaBadge(status) {
        const s = status || '未知';
        let cls = 'offline';
        if (s.includes('耗尽')) cls = 'danger';
        else if (s.includes('接近') || s.includes('偏低')) cls = 'warning';
        else if (s.includes('中等')) cls = 'info';
        else if (s.includes('充足')) cls = 'online';
        return makeBadge(s, cls);
    }
    function qualityBadge(lv) {
        const m = { T1: 'online', T2: 'warning', T3: 'offline' };
        return makeBadge(lv || '-', m[lv] || 'offline');
    }
    function makeCell(text, code) {
        const td = document.createElement('td');
        if (code) {
            const el = document.createElement('code');
            el.textContent = text;
            td.appendChild(el);
        } else {
            td.textContent = text;
        }
        return td;
    }
    function fillTable(body, rows, colSpan, emptyMsg) {
        body.innerHTML = '';
        if (!rows.length) {
            const tr = document.createElement('tr');
            const td = document.createElement('td');
            td.colSpan = colSpan;
            td.style.textAlign = 'center';
            td.style.color = '#888';
            td.textContent = emptyMsg;
            tr.appendChild(td);
            body.appendChild(tr);
            return;
        }
        const frag = document.createDocumentFragment();
        rows.forEach(tr => frag.appendChild(tr));
        body.appendChild(frag);
    }
    async function fetchResources() {
        try {
            const res = await fetch('/api/resources');
            const data = await res.json().catch(() => null);
            if (res.ok && data && data.ok) {
                state.resources = data;
                renderResources();
            } else {
                renderResourcesError((data && (data.detail || data.error)) || '数据桥不可用');
            }
        } catch (err) {
            renderResourcesError('无法获取资源清单');
        }
    }
    function renderResources() {
        const d = state.resources;
        if (!d) return;
        const meta = d.meta || {};
        const counts = d.counts || {};

        document.getElementById('res-cap-count').innerText = counts.capabilities ?? '—';
        document.getElementById('res-inst-count').innerText = counts.instances ?? '—';

        const srcEl = document.getElementById('res-source');
        const isRemote = d.source === 'remote';
        srcEl.innerText = isRemote ? '线上 GitHub Pages' : '本地 public 产物';
        srcEl.classList.toggle('text-emerald', isRemote);
        srcEl.classList.toggle('text-rose', !isRemote);

        document.getElementById('res-generated').innerText = (meta.generated_at || '').slice(0, 16) || '—';

        // 元信息条：build_id / 桥版本 / 抓取时间 / 缓存命中（验证链路的"证明值"）
        document.getElementById('res-build-id').innerText = meta.build_id || '—';
        document.getElementById('res-bridge-version').innerText = meta.bridge_version ?? '—';
        document.getElementById('res-fetched-at').innerText = (d.fetched_at || '—').slice(0, 19).replace('T', ' ');
        const cacheEl = document.getElementById('res-cache-hit');
        cacheEl.innerText = d.cache_hit ? '命中' : '未命中';
        cacheEl.className = d.cache_hit ? 'text-emerald' : 'text-rose';

        // 陈旧阈值由桥端 stale_after_hours 决定，前端不再硬编码 48h
        const freshEl = document.getElementById('res-fresh');
        freshEl.innerHTML = '';
        if (meta.fresh === false) freshEl.appendChild(makeBadge('数据已陈旧 (>' + (meta.stale_after_hours ?? 48) + 'h)', 'warning'));
        else if (meta.fresh === true) freshEl.appendChild(makeBadge('数据新鲜', 'online'));
        else freshEl.appendChild(makeBadge('新鲜度未知', 'offline'));

        // 本地回退：黄标而非红色"故障"——数据仍可用，只是来自本地副本
        if (d.fallback) {
            freshEl.appendChild(makeBadge('本地回退', 'warning'));
        }

        const capBody = document.getElementById('res-capabilities-body');
        const instBody = document.getElementById('res-instances-body');
        const caps = d.capabilities || [];
        const insts = d.instances || [];

        const capRows = caps.map(c => {
            const tr = document.createElement('tr');
            tr.appendChild(makeCell(c.capability_id || '', true));
            tr.appendChild(makeCell(c['资源名称'] || '', false));
            tr.appendChild(makeCell(c['类别'] || '', false));
            tr.appendChild(makeCell(c['逻辑模型'] || '', false));
            const tdQ = document.createElement('td');
            tdQ.appendChild(qualityBadge(c['质量等级']));
            tr.appendChild(tdQ);
            tr.appendChild(makeCell(c['调用方式'] || '', false));
            tr.appendChild(makeCell(c['模型族'] || '', false));
            return tr;
        });
        fillTable(capBody, capRows, 7, '暂无能力数据');

        const instRows = insts.map(i => {
            const tr = document.createElement('tr');
            tr.appendChild(makeCell(i.instance_id || '', true));
            tr.appendChild(makeCell(i['平台'] || '', false));
            tr.appendChild(makeCell(i['实际模型名'] || '', false));
            tr.appendChild(makeCell(i['所属能力'] || '', true));
            tr.appendChild(makeCell(i['额度单位'] || '', false));
            tr.appendChild(makeCell(i['重置规则'] || '', false));
            const tdQ = document.createElement('td');
            tdQ.appendChild(quotaBadge(i['额度状态']));
            tr.appendChild(tdQ);
            return tr;
        });
        fillTable(instBody, instRows, 7, '暂无实例数据');
    }
    function renderResourcesError(msg) {
        const capBody = document.getElementById('res-capabilities-body');
        const instBody = document.getElementById('res-instances-body');
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = 7;
        td.style.textAlign = 'center';
        td.style.color = 'var(--rose)';
        td.textContent = '⚠️ ' + msg;
        tr.appendChild(td);
        if (capBody) { capBody.innerHTML = ''; capBody.appendChild(tr.cloneNode(true)); }
        if (instBody) { instBody.innerHTML = ''; instBody.appendChild(tr); }
        document.getElementById('res-source').innerText = '—';
        document.getElementById('res-generated').innerText = '—';
        document.getElementById('res-fresh').innerHTML = '';
        document.getElementById('res-build-id').innerText = '—';
        document.getElementById('res-bridge-version').innerText = '—';
        document.getElementById('res-fetched-at').innerText = '—';
        const cacheEl = document.getElementById('res-cache-hit');
        if (cacheEl) { cacheEl.innerText = '—'; cacheEl.className = ''; }
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
        if (state.currentTab === 'resources') fetchResources();
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

/* app.js —— 组件编排器画布观察窗 SSE 消费与动态UI渲染逻辑 */

let slotsMap = {};
let eventLogList = [];
let startTime = Date.now();
let totalSlots = 5;
let completedSlots = 0;
let es = null;
let receivedRealEvent = false;
let demoStarted = false;
let emptyTimer = null;

const PHASES = ["framework", "scan", "asset_fill", "verify", "deliver"];

function initCanvas() {
  updateTimer();
  setInterval(updateTimer, 1000);

  // 尝试连接真实 SSE 端点；仅当从未收到真实事件时才回退 Mock
  try {
    es = new EventSource('/api/orchestrator/stream');
    es.onmessage = (ev) => {
      try {
        const d = JSON.parse(ev.data);
        receivedRealEvent = true;
        if (emptyTimer) { clearTimeout(emptyTimer); emptyTimer = null; }
        if (d.event === 'stream_end') {
          es.close();
          updatePhaseTimeline('deliver');
          return;
        }
        handleSSEEvent(d);
      } catch(e){}
    };
    es.onerror = () => {
      es.close();
      if (!receivedRealEvent) showEmptyState();
    };
  } catch(e) {
    if (!receivedRealEvent) showEmptyState();
  }

  // serve-only 模式：SSE 静默 keepalive 无事件 → 数秒后显示空态引导（否则页面一直空白 = 用户眼中的「打不开」）
  emptyTimer = setTimeout(() => {
    if (!receivedRealEvent) showEmptyState();
  }, 4000);
}

function startMockStream() {
  if (!window.MOCK_EVENT_SEQUENCE || demoStarted) return;
  demoStarted = true;
  window.MOCK_EVENT_SEQUENCE.forEach((item, idx) => {
    setTimeout(() => {
      handleSSEEvent(item);
    }, idx * 900);
  });
}

function startDemo() {
  startMockStream();
}

function showEmptyState() {
  const grid = document.getElementById('slot-grid');
  if (receivedRealEvent || demoStarted || !grid) return;
  grid.innerHTML = `
    <div class="empty-state">
      <svg viewBox="0 0 24 24" width="42" height="42" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="14" rx="2"/><path d="M3 10h18M8 2l1 2M16 2l1 2M7 14h4M7 17h8"/></svg>
      <h2>暂无编排任务</h2>
      <p>当前为常驻观察模式（serve-only）。编排器画布会实时直播课件生成的完整事件流：框架生成 → 槽位扫描 → 资产填充 → 规则校验 → 交付完工。</p>
      <p class="hint">在终端启动一次编排任务（canvas_server.py --topic "主题" --lesson L27）即可看到真实事件流；下面是模拟演示。</p>
      <button type="button" class="btn" onclick="startDemo()">▶ 运行演示流程</button>
    </div>`;
}

function handleSSEEvent(data) {
  eventLogList.push(data);
  renderLogItem(data);
  updatePhaseTimeline(data.phase);

  // 真实槽位总数（scan done 事件携带 total）
  if (typeof data.total === 'number' && data.total > 0) {
    totalSlots = data.total;
    updateProgress();
  }

  if (data.slot && data.slot !== 'main' && data.slot !== 'all') {
    if (!slotsMap[data.slot]) {
      slotsMap[data.slot] = {
        id: data.slot,
        topic: data.detail || '媒体槽位',
        status: 'pending',
        site: data.site || '自动调度',
        preview: null
      };
    }

    const slotObj = slotsMap[data.slot];
    if (data.event === 'generating' || data.event === 'prompt_ready') {
      slotObj.status = 'generating';
    } else if (data.event === 'retry') {
      slotObj.status = 'retry';
    } else if (data.event === 'done') {
      slotObj.status = 'done';
      if (data.preview) slotObj.preview = data.preview;
      completedSlots = Math.min(totalSlots, completedSlots + 1);
    } else if (data.event === 'failed') {
      slotObj.status = 'failed';
    }

    renderSlotGrid();
  }

  updateProgress();
}

function updatePhaseTimeline(currentPhase) {
  const currentIdx = PHASES.indexOf(currentPhase);
  PHASES.forEach((p, idx) => {
    const el = document.getElementById('step-' + p);
    if (!el) return;
    el.classList.remove('active', 'done');
    if (idx < currentIdx) {
      el.classList.add('done');
      el.querySelector('.step-dot').innerText = '✓';
    } else if (idx === currentIdx) {
      el.classList.add('active');
    }
  });
}

function renderSlotGrid() {
  const grid = document.getElementById('slot-grid');
  if (!grid) return;
  grid.innerHTML = '';

  Object.values(slotsMap).forEach(slot => {
    const card = document.createElement('div');
    card.className = 'slot-card';

    let badgeClass = 'badge-pending';
    let badgeText = '⏳ 待处理';
    if (slot.status === 'generating') { badgeClass = 'badge-generating'; badgeText = '🔄 生成中'; }
    else if (slot.status === 'done') { badgeClass = 'badge-done'; badgeText = '✅ 完成'; }
    else if (slot.status === 'retry') { badgeClass = 'badge-retry'; badgeText = '⚠️ 重试中'; }
    else if (slot.status === 'failed') { badgeClass = 'badge-failed'; badgeText = '❌ 失败'; }

    let previewHTML = `<div style="font-size:12px;color:var(--text-muted);">暂无预览</div>`;
    if (slot.preview) {
      previewHTML = `<img src="${slot.preview}" alt="${slot.topic}">`;
    }

    card.innerHTML = `
      <div class="slot-head">
        <span class="slot-id">#${slot.id}</span>
        <span class="slot-badge ${badgeClass}">${badgeText}</span>
      </div>
      <div class="slot-topic">主题: ${slot.topic}</div>
      <div style="font-size:12px;color:var(--text-muted);">调度站点: <b style="color:var(--primary);">${slot.site}</b></div>
      <div class="preview-container">${previewHTML}</div>
    `;

    grid.appendChild(card);
  });
}

function renderLogItem(data) {
  const stream = document.getElementById('log-stream');
  const countEl = document.getElementById('event-count');
  if (!stream) return;

  const item = document.createElement('div');
  const isErr = data.event === 'failed' || data.event === 'retry';
  const isSuccess = data.event === 'done';
  item.className = `log-item ${isErr ? 'error' : (isSuccess ? 'success' : '')}`;

  item.innerHTML = `
    <div style="display:flex;justify-content:space-between;color:var(--text-muted);font-size:11px;">
      <span>[${data.ts || new Date().toLocaleTimeString()}] ${data.phase}</span>
      <span>${data.slot}</span>
    </div>
    <div style="font-weight:700;margin-top:2px;">${data.event}: ${data.detail || ''}</div>
  `;

  stream.appendChild(item);
  stream.scrollTop = stream.scrollHeight;
  if (countEl) countEl.innerText = `${eventLogList.length} 条事件`;
}

function updateProgress() {
  const pText = document.getElementById('progress-text');
  if (pText) pText.innerText = `${completedSlots}/${totalSlots}`;
}

function updateTimer() {
  const elapsed = Math.floor((Date.now() - startTime) / 1000);
  const m = String(Math.floor(elapsed / 60)).padStart(2, '0');
  const s = String(elapsed % 60).padStart(2, '0');
  const tText = document.getElementById('timer-text');
  if (tText) tText.innerText = `${m}:${s}`;
}

function sendConfirmAction() {
  fetch('/api/orchestrator/confirm', { method: 'POST' })
    .then(r => r.json())
    .then(d => alert('✅ L2 关键节点确认提交成功！'))
    .catch(e => alert('模拟环境：已发送确认指令'));
}

window.onload = initCanvas;

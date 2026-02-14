async function fetchCards() {
  const response = await fetch('/api/cards');
  if (!response.ok) {
    return [];
  }
  const data = await response.json();
  return data.cards || [];
}

function parseJsonMap(raw) {
  if (!raw) return {};
  try {
    const payload = JSON.parse(String(raw));
    return (payload && typeof payload === 'object' && !Array.isArray(payload)) ? payload : {};
  } catch (_) {
    return {};
  }
}

async function fetchSetupStatus() {
  const response = await fetch('/api/setup-status');
  if (!response.ok) {
    return { needs_setup: false };
  }
  return response.json();
}

async function hydrateCards() {
  const cards = await fetchCards();
  const cardsList = document.getElementById('cardsList');
  if (cardsList) {
    cardsList.innerHTML = cards.length
      ? cards.map((card) => {
        const category = parseJsonMap(card.category_multipliers);
        const channel = parseJsonMap(card.channel_multipliers);
        const merchant = parseJsonMap(card.merchant_multipliers);
        return `<li>${card.card_id} · ${card.bank} · ${card.network} · base ${card.reward_rate} · fee ₹${card.annual_fee || 0} · milestone ₹${card.milestone_spend || 0}/₹${card.milestone_bonus || 0}`
          + `<br/><small>category=${JSON.stringify(category)} channel=${JSON.stringify(channel)} merchant=${JSON.stringify(merchant)}</small> <button data-card-id="${card.card_id}" class="delete-card-btn">Remove</button></li>`;
      }).join('')
      : '<li>No cards loaded yet.</li>';

    cardsList.querySelectorAll('.delete-card-btn').forEach((button) => {
      button.addEventListener('click', async () => {
        const cardId = button.getAttribute('data-card-id');
        await fetch(`/api/cards/${encodeURIComponent(cardId)}`, { method: 'DELETE' });
        hydrateCards();
      });
    });
  }

  const cardSelect = document.getElementById('cardSelect');
  if (cardSelect) {
    cardSelect.innerHTML = cards.length
      ? cards.map((card) => `<option value="${card.card_id}">${card.card_id} · ${card.bank}</option>`).join('')
      : '<option value="">Upload cards first</option>';
  }

  const status = await fetchSetupStatus();
  const onboardingBanner = document.getElementById('onboardingBanner');
  if (onboardingBanner) {
    onboardingBanner.style.display = status.needs_setup ? 'block' : 'none';
  }
}

const uploadForm = document.getElementById('cardsUploadForm');
const addForm = document.getElementById('cardAddForm');
const recommendationForm = document.getElementById('recommendationForm');
const discoverCardsBtn = document.getElementById('discoverCardsBtn');
const loadDailyScanBtn = document.getElementById('loadDailyScanBtn');

if (uploadForm) {
  uploadForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const resultEl = document.getElementById('uploadResult');
    const payload = new FormData(uploadForm);
    const response = await fetch('/api/cards/upload', { method: 'POST', body: payload });
    const data = await response.json();
    if (!response.ok) {
      resultEl.textContent = data.error || 'Upload failed';
      return;
    }
    resultEl.textContent = `Uploaded ${data.count} card(s).`;
    hydrateCards();
  });
}

if (addForm) {
  addForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const resultEl = document.getElementById('uploadResult');
    const formData = new FormData(addForm);
    const payload = {
      card_id: formData.get('card_id'),
      bank: formData.get('bank'),
      network: formData.get('network'),
      reward_rate: Number(formData.get('reward_rate')),
      monthly_reward_cap: Number(formData.get('monthly_reward_cap')),
      annual_fee: Number(formData.get('annual_fee') || 0),
      milestone_spend: Number(formData.get('milestone_spend') || 0),
      milestone_bonus: Number(formData.get('milestone_bonus') || 0),
      category_multipliers: parseJsonMap(formData.get('category_multipliers')),
      channel_multipliers: parseJsonMap(formData.get('channel_multipliers')),
      merchant_multipliers: parseJsonMap(formData.get('merchant_multipliers')),
    };
    const response = await fetch('/api/cards', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      resultEl.textContent = data.error || 'Add card failed';
      return;
    }
    resultEl.textContent = `Saved card ${data.card_id}.`;
    addForm.reset();
    hydrateCards();
  });
}

if (discoverCardsBtn) {
  discoverCardsBtn.addEventListener('click', async () => {
    const response = await fetch('/api/cards/catalog');
    const data = await response.json();
    const catalogList = document.getElementById('catalogList');
    const cards = data.cards || [];
    catalogList.innerHTML = cards.length
      ? cards.map((card) => `<li>${card.name} <small>(${card.source})</small></li>`).join('')
      : '<li>No card mentions discovered yet.</li>';
  });
}

if (loadDailyScanBtn) {
  loadDailyScanBtn.addEventListener('click', async () => {
    const response = await fetch('/api/daily-scan');
    const data = await response.json();
    const snapshot = data.snapshot || {};
    const container = document.getElementById('dailyScanResult');
    const mentions = snapshot.bank_and_reward_mentions || [];
    container.innerHTML = `<p>Generated at: ${snapshot.generated_at || 'N/A'}</p><p>Mentions: ${mentions.length}</p>`;
  });
}

if (recommendationForm) {
  recommendationForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const formData = new FormData(recommendationForm);
    const payload = {
      merchant: formData.get('merchant'),
      amount: Number(formData.get('amount')),
      category: formData.get('category') || 'other',
      merchant_url: formData.get('merchant_url'),
      channel: formData.get('channel'),
      split: formData.get('split') === 'on',
    };

    const response = await fetch('/api/recommend', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    const container = document.getElementById('recommendationResult');

    if (!response.ok) {
      container.textContent = data.error || 'Unable to process recommendation';
      return;
    }

    let html = '<h3>Recommended card order</h3>';
    data.recommendations.forEach((row, i) => {
      html += `<div class="reco-row"><strong>${i + 1}. ${row.card_id}</strong><br/>`
        + `Estimated savings: ₹${row.savings.toFixed(2)}<br/>Reason: ${row.reason}</div>`;
    });

    html += `<h3>Merchant scan</h3><p>${data.merchant_insights.title || 'No merchant title found'}</p>`;
    html += `<p>Hints: ${(data.merchant_insights.hints || []).join(', ') || 'none'}</p>`;
    html += `<h3>LLM refined response</h3><pre>${data.refined_response}</pre>`;
    html += `<h3>Social scan</h3><p>${data.insights.summary}</p><div class="source-links">`;
    data.insights.sources.forEach((source) => {
      html += `<a href="${source.url}" target="_blank" rel="noopener noreferrer">${source.name}</a>`;
    });
    html += '</div><ul>';
    data.insights.items.forEach((item) => {
      html += `<li><a href="${item.url}" target="_blank" rel="noopener noreferrer">${item.title}</a> (${item.source})</li>`;
    });
    html += '</ul>';

    container.innerHTML = html;
  });
}

hydrateCards();

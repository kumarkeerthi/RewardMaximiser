async function fetchCards() {
  const response = await fetch('/api/cards');
  if (!response.ok) {
    return [];
  }
  const data = await response.json();
  return data.cards || [];
}

async function hydrateCards() {
  const cards = await fetchCards();
  const cardsList = document.getElementById('cardsList');
  if (cardsList) {
    cardsList.innerHTML = cards.length
      ? cards.map((card) => `<li>${card.card_id} · ${card.bank} · ${card.network} · reward rate ${card.reward_rate}</li>`).join('')
      : '<li>No cards loaded yet.</li>';
  }

  const cardSelect = document.getElementById('cardSelect');
  if (cardSelect) {
    cardSelect.innerHTML = cards.length
      ? cards.map((card) => `<option value="${card.card_id}">${card.card_id} · ${card.bank}</option>`).join('')
      : '<option value="">Upload cards first</option>';
  }
}

const uploadForm = document.getElementById('cardsUploadForm');
const recommendationForm = document.getElementById('recommendationForm');

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

if (recommendationForm) {
  recommendationForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const formData = new FormData(recommendationForm);
    const payload = {
      merchant: formData.get('merchant'),
      amount: Number(formData.get('amount')),
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

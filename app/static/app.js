const state = {
  contacts: [],
  templates: [],
  campaigns: [],
  jobs: [],
  contactEditId: null,
  planner: {
    open: false,
    campaignId: null,
    selectedContactIds: [],
    attachment: null,
  },
  apiOnline: false,
  loading: false,
};

const statusLabels = {
  draft: 'Rascunho',
  scheduled: 'Agendada',
  sending: 'Enviando',
  completed: 'Concluída',
  completed_with_issues: 'Com problemas',
  pending: 'Na fila',
  processing: 'Processando',
  sent: 'Enviado',
  failed: 'Falhou',
  uncertain: 'Incerto',
  suppressed: 'Suprimido',
};

const statusColors = {
  sent: 'var(--purple)',
  pending: 'var(--cyan)',
  processing: 'var(--cyan)',
  failed: 'var(--red)',
  uncertain: 'var(--orange)',
  suppressed: 'var(--ink-faint)',
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#039;', '"': '&quot;',
  })[character]);
}

function formatDate(value) {
  if (!value) return '—';
  return new Intl.DateTimeFormat('pt-BR', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
}

function formatShortDate(value) {
  if (!value) return 'Sem agendamento';
  return new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: 'short' }).format(new Date(value));
}

function getToken() {
  return localStorage.getItem('email-automation-api-token') || '';
}

function setContactFeedback(message, type = '') {
  const feedback = $('#contact-form-feedback');
  feedback.textContent = message;
  feedback.className = `form-feedback ${type}`.trim();
}

function parseContactEmails(value) {
  return [...new Set(value.split(/[\s,;]+/).map((email) => email.trim()).filter(Boolean))];
}

function openContactForm(contact = null) {
  state.contactEditId = contact ? contact.id : null;
  $('#contact-form-panel').classList.remove('hidden');
  $('#contact-form-title').textContent = contact ? 'Editar contato' : 'Novo contato';
  $('#contact-submit').innerHTML = contact ? 'Salvar alterações <span>→</span>' : 'Salvar contatos <span>→</span>';
  $('#contact-emails').value = contact ? contact.email : '';
  $('#contact-name').value = contact?.display_name || '';
  $('#contact-organization').value = contact?.organization || '';
  $('#contact-role').value = contact?.role_title || '';
  setContactFeedback('');
  $('#contact-emails').focus();
}

function closeContactForm() {
  state.contactEditId = null;
  $('#contact-form-panel').classList.add('hidden');
  $('#contact-form').reset();
  $('#contact-form-title').textContent = 'Novo contato';
  $('#contact-submit').innerHTML = 'Salvar contatos <span>→</span>';
  setContactFeedback('');
}

async function submitContacts(event) {
  event.preventDefault();
  const token = getToken();
  if (!token) {
    setContactFeedback('Configure o Bearer token antes de salvar contatos.', 'error');
    navigate('settings');
    return;
  }

  const emails = parseContactEmails($('#contact-emails').value);
  if (!emails.length) {
    setContactFeedback('Informe pelo menos um endereço de e-mail.', 'error');
    return;
  }

  const submitButton = $('#contact-submit');
  submitButton.disabled = true;
  submitButton.textContent = 'Salvando…';
  const sharedFields = {
    display_name: $('#contact-name').value.trim() || null,
    organization: $('#contact-organization').value.trim() || null,
    role_title: $('#contact-role').value.trim() || null,
  };

  if (state.contactEditId !== null) {
    if (emails.length !== 1) {
      submitButton.disabled = false;
      submitButton.innerHTML = 'Salvar alterações <span>→</span>';
      setContactFeedback('Na edição, informe exatamente um endereço.', 'error');
      return;
    }
    try {
      await apiFetch(`/api/v1/contacts/${state.contactEditId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: emails[0], ...sharedFields }),
      });
      setContactFeedback('Contato atualizado com sucesso.', 'success');
      showToast('Contato atualizado.');
      closeContactForm();
      await loadData();
    } catch (error) {
      setContactFeedback(error.status === 409 ? 'Já existe um contato com esse endereço.' : 'Não foi possível atualizar o contato.', 'error');
    } finally {
      submitButton.disabled = false;
      submitButton.innerHTML = 'Salvar alterações <span>→</span>';
    }
    return;
  }

  setContactFeedback('Adicionando contatos…');
  let created = 0;
  let duplicates = 0;
  let failed = 0;
  for (const email of emails) {
    try {
      await apiFetch('/api/v1/contacts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, ...sharedFields }),
      });
      created += 1;
    } catch (error) {
      if (error.status === 409) duplicates += 1;
      else failed += 1;
    }
  }

  submitButton.disabled = false;
  submitButton.innerHTML = 'Salvar contatos <span>→</span>';
  if (created) {
    $('#contact-emails').value = '';
    setContactFeedback(`${created} contato(s) adicionado(s)${duplicates ? `; ${duplicates} já existia(m)` : ''}${failed ? `; ${failed} falhou(aram)` : ''}.`, 'success');
    await loadData();
    showToast('Contatos atualizados.');
  } else if (duplicates && !failed) {
    setContactFeedback('Todos os endereços informados já estão cadastrados.', 'error');
  } else {
    setContactFeedback('Não foi possível salvar os contatos. Verifique o token e a conexão com o banco.', 'error');
  }
}

function setConnection(online, detail) {
  state.apiOnline = online;
  const dot = $('#sidebar-status-dot');
  dot.className = `status-dot ${online ? 'online' : 'offline'}`;
  $('#sidebar-status').textContent = online ? 'API online' : 'API indisponível';
  $('#sidebar-status-detail').textContent = detail;
  $('#health-api').textContent = online ? 'Respondendo' : 'Indisponível';
  $('#health-badge').textContent = online ? 'Online' : 'Offline';
  $('#health-badge').classList.toggle('online', online);
}

async function apiFetch(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = getToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  headers.set('Accept', 'application/json');
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    let detail = '';
    try {
      const payload = await response.json();
      detail = typeof payload.detail === 'string' ? payload.detail : '';
    } catch {
      // Keep the HTTP status when the API did not return JSON.
    }
    const error = new Error(detail || `HTTP ${response.status}`);
    error.status = response.status;
    error.detail = detail;
    throw error;
  }
  if (response.status === 204) return null;
  return response.json();
}

async function checkHealth() {
  try {
    await apiFetch('/health/live');
    setConnection(true, 'Processo respondendo');
    return true;
  } catch {
    setConnection(false, 'Não foi possível conectar');
    return false;
  }
}

async function loadData() {
  state.loading = true;
  const token = getToken();
  $('#auth-notice').classList.toggle('hidden', Boolean(token));
  if (!token) {
    state.contacts = [];
    state.templates = [];
    state.campaigns = [];
    state.jobs = [];
    renderAll();
    state.loading = false;
    return;
  }

  const [contacts, templates, campaigns] = await Promise.all([
    apiFetch('/api/v1/contacts?limit=200').catch(() => []),
    apiFetch('/api/v1/templates?limit=200').catch(() => []),
    apiFetch('/api/v1/campaigns?limit=200').catch(() => []),
  ]);
  state.contacts = Array.isArray(contacts) ? contacts : [];
  state.templates = Array.isArray(templates) ? templates : [];
  state.campaigns = Array.isArray(campaigns) ? campaigns : [];

  const jobLists = await Promise.all(state.campaigns.map((campaign) =>
    apiFetch(`/api/v1/campaigns/${campaign.id}/jobs?limit=200`).catch(() => []),
  ));
  state.jobs = jobLists.flat().map((job) => ({ ...job }));
  renderAll();
  state.loading = false;
}

function statusBadge(status) {
  const normalized = status === 'completed_with_issues' ? 'issue' : status;
  return `<span class="badge badge-${escapeHtml(normalized)}">${escapeHtml(statusLabels[status] || status)}</span>`;
}

function renderMetrics() {
  const activeCampaigns = state.campaigns.filter((campaign) => ['scheduled', 'sending'].includes(campaign.status)).length;
  const queueJobs = state.jobs.filter((job) => ['pending', 'processing'].includes(job.status)).length;
  const finishedJobs = state.jobs.filter((job) => ['sent', 'failed', 'uncertain', 'suppressed'].includes(job.status)).length;
  const sentJobs = state.jobs.filter((job) => job.status === 'sent').length;
  const deliveryRate = finishedJobs ? Math.round((sentJobs / finishedJobs) * 100) : null;

  $('#metric-contacts').textContent = state.contacts.length || '0';
  $('#metric-campaigns').textContent = activeCampaigns;
  $('#metric-jobs').textContent = queueJobs;
  $('#metric-delivery').textContent = deliveryRate === null ? '—' : `${deliveryRate}%`;
  $('#metric-contacts-detail').textContent = state.contacts.length ? `${state.contacts.filter((contact) => contact.status === 'active').length} ativos` : 'nenhum contato carregado';
  $('#metric-campaigns-detail').textContent = activeCampaigns ? 'em execução ou agendadas' : 'nenhuma em andamento';
  $('#metric-jobs-detail').textContent = state.jobs.length ? `${state.jobs.length} jobs no total` : 'a fila está vazia';
  $('#metric-delivery-detail').textContent = finishedJobs ? `${sentJobs} de ${finishedJobs} concluídos` : 'sem envios concluídos';
}

function renderActivity() {
  const campaigns = state.campaigns.slice(-7);
  const source = campaigns.length ? campaigns : [{ name: 'Sem dados', id: 0 }];
  const columns = source.map((campaign) => {
    const jobs = state.jobs.filter((job) => job.campaign_id === campaign.id);
    const sent = jobs.filter((job) => job.status === 'sent').length;
    const pending = jobs.filter((job) => ['pending', 'processing'].includes(job.status)).length;
    const issue = jobs.filter((job) => ['failed', 'uncertain'].includes(job.status)).length;
    const max = Math.max(sent, pending, issue, 1);
    return `<div class="chart-column">
      <div class="bar sent" style="height:${Math.max(3, (sent / max) * 100)}%" data-value="${sent} enviados" title="${escapeHtml(campaign.name)}: ${sent} enviados"></div>
      <div class="bar pending" style="height:${Math.max(3, (pending / max) * 100)}%" data-value="${pending} na fila" title="${escapeHtml(campaign.name)}: ${pending} na fila"></div>
      <div class="bar issue" style="height:${Math.max(3, (issue / max) * 100)}%" data-value="${issue} problemas" title="${escapeHtml(campaign.name)}: ${issue} problemas"></div>
    </div>`;
  }).join('');
  const labels = source.map((campaign) => `<span>${escapeHtml((campaign.name || 'Sem dados').slice(0, 11))}</span>`).join('');
  $('#activity-chart').innerHTML = `<div class="chart-bars">${columns}</div><div class="chart-labels">${labels}</div>`;
}

function renderStatus() {
  const statuses = ['sent', 'pending', 'processing', 'failed', 'uncertain', 'suppressed'];
  const counts = Object.fromEntries(statuses.map((status) => [status, state.jobs.filter((job) => job.status === status).length]));
  const total = Object.values(counts).reduce((sum, value) => sum + value, 0);
  const segments = [];
  let cursor = 0;
  statuses.forEach((status) => {
    if (counts[status]) {
      const end = cursor + (counts[status] / total) * 100;
      segments.push(`${statusColors[status]} ${cursor}% ${end}%`);
      cursor = end;
    }
  });
  const chart = $('#status-chart');
  chart.className = `status-chart ${total ? '' : 'empty'}`;
  chart.style.background = total ? `conic-gradient(${segments.join(', ')})` : '';
  const oldTotal = chart.dataset.total;
  chart.dataset.total = total;
  chart.style.setProperty('--chart-total', `'${total}'`);
  chart.innerHTML = '';
  const center = document.createElement('span');
  center.textContent = total;
  center.style.cssText = 'position:absolute;z-index:1;inset:0;display:grid;place-items:center;color:#f3f6fa;font-family:"Space Grotesk";font-size:21px;';
  chart.append(center);
  $('#status-table').innerHTML = statuses.map((status) => `<div class="status-row"><span class="status-name"><i class="status-dot-small" style="background:${statusColors[status]}"></i>${escapeHtml(statusLabels[status])}</span><strong>${counts[status]}</strong></div>`).join('');
  if (oldTotal !== String(total)) chart.setAttribute('aria-label', `${total} jobs distribuídos por estado`);
}

function renderCampaignTable() {
  const body = $('#campaigns-table-body');
  if (!state.campaigns.length) {
    body.innerHTML = `<tr><td colspan="5"><div class="empty-state"><strong>Nenhuma campanha para mostrar</strong><p>Crie uma campanha pela API para vê-la neste painel.</p></div></td></tr>`;
    return;
  }
  body.innerHTML = state.campaigns.slice(0, 8).map((campaign) => {
    const jobs = state.jobs.filter((job) => job.campaign_id === campaign.id);
    return `<tr><td><span class="campaign-name">${escapeHtml(campaign.name)}</span><span class="campaign-id">CAM-${String(campaign.id).padStart(4, '0')}</span></td><td>${statusBadge(campaign.status)}</td><td>${escapeHtml(formatShortDate(campaign.scheduled_at))}</td><td>${jobs.length || '—'}</td><td><button class="text-button" data-campaign-id="${campaign.id}">Abrir</button></td></tr>`;
  }).join('');
}

function renderContacts() {
  const active = state.contacts.filter((contact) => contact.status === 'active').length;
  $('#contacts-summary').innerHTML = `<div class="summary-chip"><strong>${state.contacts.length}</strong><span>Total de contatos</span></div><div class="summary-chip"><strong>${active}</strong><span>Ativos</span></div><div class="summary-chip"><strong>${state.contacts.length - active}</strong><span>Inativos</span></div>`;
  const body = $('#contacts-table-body');
  body.innerHTML = state.contacts.length ? state.contacts.map((contact) => `<tr><td><span class="campaign-name">${escapeHtml(contact.email)}</span></td><td>${escapeHtml(contact.display_name || '—')}</td><td>${escapeHtml(contact.organization || '—')}</td><td>${statusBadge(contact.status)}</td><td>${escapeHtml(formatDate(contact.updated_at))}</td><td><div class="table-actions"><button class="table-action" data-edit-contact="${contact.id}">Editar</button><button class="table-action danger" data-delete-contact="${contact.id}">Excluir</button></div></td></tr>`).join('') : `<tr><td colspan="6"><div class="empty-state"><strong>Sem contatos carregados</strong><p>Informe um token válido e verifique se o banco está acessível.</p></div></td></tr>`;
}

function renderTemplates() {
  const grid = $('#templates-grid');
  grid.innerHTML = state.templates.length ? state.templates.map((template) => `<article class="template-card"><h3>${escapeHtml(template.name)}</h3><p><strong>${escapeHtml(template.subject)}</strong><br>${escapeHtml(template.body_text)}</p><div class="card-meta"><span>Template #${template.id}</span><span>${escapeHtml(formatShortDate(template.updated_at))}</span></div></article>`).join('') : `<article class="panel" style="grid-column:1/-1"><div class="empty-state"><strong>Sem templates carregados</strong><p>Templates criados pela API aparecerão aqui.</p></div></article>`;
}

function toDateTimeLocal(value) {
  if (!value) return '';
  const date = new Date(value);
  const pad = (part) => String(part).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function renderCampaignPlannerOptions() {
  const select = $('#campaign-template');
  if (!select) return;
  const selected = select.value;
  select.innerHTML = state.templates.map((template) => `<option value="${template.id}">${escapeHtml(template.name)} · ${escapeHtml(template.subject)}</option>`).join('');
  if (selected && state.templates.some((template) => String(template.id) === selected)) select.value = selected;
  else if (state.templates[0]) select.value = state.templates[0].id;
}

function renderRecipientPicker() {
  const list = $('#recipient-list');
  if (!list) return;
  const query = $('#recipient-search').value.trim().toLowerCase();
  const visible = state.contacts.filter((contact) => {
    const haystack = `${contact.email} ${contact.display_name || ''} ${contact.organization || ''}`.toLowerCase();
    return !query || haystack.includes(query);
  });
  $('#recipient-count').textContent = `${state.planner.selectedContactIds.length} selecionado(s)`;
  list.innerHTML = visible.length ? visible.map((contact) => {
    const selected = state.planner.selectedContactIds.includes(contact.id);
    const disabled = contact.status !== 'active';
    return `<label class="recipient-option ${disabled ? 'disabled' : ''}"><input type="checkbox" data-recipient-id="${contact.id}" ${selected ? 'checked' : ''} ${disabled ? 'disabled' : ''}><span class="recipient-check"></span><span class="recipient-copy"><strong>${escapeHtml(contact.email)}</strong><small>${escapeHtml(contact.display_name || contact.organization || (disabled ? 'Contato inativo' : 'Pronto para receber'))}</small></span>${disabled ? '<span class="recipient-state">inativo</span>' : ''}</label>`;
  }).join('') : `<div class="empty-state"><strong>Nenhum contato encontrado</strong><p>Cadastre um contato ou ajuste o filtro.</p></div>`;
}

function openCampaignPlanner(campaign = null) {
  state.planner.open = true;
  state.planner.campaignId = campaign?.id || null;
  const jobs = campaign ? state.jobs.filter((job) => job.campaign_id === campaign.id) : [];
  state.planner.selectedContactIds = jobs.map((job) => job.contact_id).filter((id) => id !== null);
  $('#campaign-planner').classList.remove('hidden');
  $('#campaign-planner-title').textContent = campaign ? 'Editar campanha' : 'Nova campanha';
  $('#campaign-id').value = campaign?.id || '';
  $('#campaign-name').value = campaign?.name || '';
  $('#campaign-subject').value = campaign?.subject || '';
  $('#campaign-attachment').value = '';
  $('#campaign-attachment-help').textContent = 'Qualquer tipo de arquivo, até 25 MB. O anexo será enviado junto com a campanha.';
  $('#delete-campaign-button').classList.toggle('hidden', !campaign);
  $('#recipient-search').value = '';
  setCampaignFeedback('');
  renderRecipientPicker();
  $('#campaign-name').focus();
}

function closeCampaignPlanner() {
  state.planner.open = false;
  state.planner.campaignId = null;
  state.planner.selectedContactIds = [];
  state.planner.attachment = null;
  $('#campaign-planner').classList.add('hidden');
  $('#campaign-form').reset();
  setCampaignFeedback('');
}

function setCampaignFeedback(message, type = '') {
  const feedback = $('#campaign-form-feedback');
  feedback.textContent = message;
  feedback.className = `form-feedback ${type}`.trim();
}

async function saveCampaign({ send = false } = {}) {
  const name = $('#campaign-name').value.trim();
  const subject = $('#campaign-subject').value.trim();
  const selectedIds = state.planner.selectedContactIds;
  const attachment = $('#campaign-attachment').files[0];
  if (!name || !subject) {
    setCampaignFeedback('Informe o título e o assunto.', 'error');
    return null;
  }
  if (!selectedIds.length) {
    setCampaignFeedback('Selecione pelo menos um destinatário.', 'error');
    return null;
  }
  if (attachment && attachment.size > 25 * 1024 * 1024) {
    setCampaignFeedback('O anexo deve ter no máximo 25 MB.', 'error');
    return null;
  }

  const draftPayload = { name, subject };
  setCampaignFeedback(send ? 'Preparando envio…' : 'Salvando rascunho…');
  try {
    let campaign;
    if (state.planner.campaignId) {
      campaign = await apiFetch(`/api/v1/campaigns/${state.planner.campaignId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(draftPayload),
      });
    } else {
      campaign = await apiFetch('/api/v1/campaigns', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(draftPayload),
      });
      state.planner.campaignId = campaign.id;
    }
    await apiFetch(`/api/v1/campaigns/${campaign.id}/recipients`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ contact_ids: selectedIds }),
    });
    if (attachment) {
      await apiFetch(`/api/v1/campaigns/${campaign.id}/attachment`, {
        method: 'POST',
        headers: {
          'Content-Type': attachment.type || 'application/octet-stream',
          'X-File-Name': encodeURIComponent(attachment.name),
        },
        body: attachment,
      });
    }
    if (send) {
      await apiFetch(`/api/v1/campaigns/${campaign.id}/schedule`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scheduled_at: new Date(Date.now() + 1000).toISOString() }),
      });
    }
    await loadData();
    closeCampaignPlanner();
    showToast(send ? 'Campanha enviada para a fila.' : 'Rascunho salvo.');
    return campaign;
  } catch (error) {
    let message = 'Não foi possível salvar ou enviar a campanha.';
    if (error.status === 401 || error.status === 403) message = 'Token inválido ou ausente. Configure o Bearer token em Configuração.';
    else if (error.status === 409) message = 'Essa campanha não está mais disponível para edição ou envio.';
    else if (error.status >= 500) message = 'A API não conseguiu acessar o banco. Confira a conexão do TiDB e veja os logs do servidor.';
    else if (error.detail) message = error.detail;
    setCampaignFeedback(message, 'error');
    return null;
  }
}

async function deleteCampaign() {
  const campaignId = state.planner.campaignId;
  if (!campaignId || !window.confirm('Excluir este rascunho e sua seleção de destinatários?')) return;
  try {
    await apiFetch(`/api/v1/campaigns/${campaignId}`, { method: 'DELETE' });
    await loadData();
    closeCampaignPlanner();
    showToast('Rascunho excluído.');
  } catch {
    setCampaignFeedback('Só é possível excluir campanhas em rascunho.', 'error');
  }
}

function renderCampaignCards() {
  const grid = $('#campaign-cards');
  grid.innerHTML = state.campaigns.length ? state.campaigns.map((campaign) => {
    const jobs = state.jobs.filter((job) => job.campaign_id === campaign.id);
    const sent = jobs.filter((job) => job.status === 'sent').length;
    const actions = campaign.status === 'draft' ? `<div class="card-actions"><button class="table-action" data-edit-campaign="${campaign.id}">Editar planejamento</button><button class="table-action danger" data-delete-campaign="${campaign.id}">Excluir</button></div>` : `<div class="card-actions"><span class="card-lock">Edição bloqueada após agendamento</span></div>`;
    return `<article class="campaign-card"><div class="card-title-row"><h3>${escapeHtml(campaign.name)}</h3>${statusBadge(campaign.status)}</div><dl><div><dt>Destinatários</dt><dd>${jobs.length}</dd></div><div><dt>Enviados</dt><dd>${sent}</dd></div><div><dt>Agendada para</dt><dd>${escapeHtml(formatDate(campaign.scheduled_at))}</dd></div><div><dt>Atualizada</dt><dd>${escapeHtml(formatShortDate(campaign.updated_at))}</dd></div></dl>${actions}</article>`;
  }).join('') : `<article class="panel" style="grid-column:1/-1"><div class="empty-state"><strong>Nenhuma campanha carregada</strong><p>Crie e agende uma campanha para acompanhar sua entrega.</p></div></article>`;
}

function renderAll() {
  renderMetrics();
  renderActivity();
  renderStatus();
  renderCampaignTable();
  renderContacts();
  renderTemplates();
  renderCampaignCards();
  if (state.planner.open) {
    renderRecipientPicker();
  }
}

function showToast(message) {
  const toast = $('#toast');
  toast.textContent = message;
  toast.classList.add('show');
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove('show'), 3000);
}

async function refresh() {
  if (state.loading) return;
  $('#refresh-button').textContent = '…';
  await checkHealth();
  try {
    await loadData();
    showToast(getToken() ? 'Dados atualizados.' : 'API online. Configure o token para ver os dados.');
  } catch {
    showToast('Não foi possível carregar os dados da API.');
  } finally {
    $('#refresh-button').textContent = '↻';
  }
}

function navigate(section) {
  $$('.nav-item, .text-button[data-section]').forEach((item) => item.classList.toggle('active', item.dataset.section === section && item.classList.contains('nav-item')));
  $$('.section-view').forEach((view) => view.classList.toggle('active', view.id === `${section}-section`));
  const labels = { overview: 'Visão geral', contacts: 'Contatos', templates: 'Templates', campaigns: 'Campanhas', settings: 'Configuração' };
  $('#page-title').textContent = labels[section] || 'Visão geral';
}

async function deleteContact(contactId) {
  const contact = state.contacts.find((item) => item.id === contactId);
  if (!contact || !window.confirm(`Excluir ${contact.email}? Jobs já existentes manterão o snapshot do endereço.`)) return;
  try {
    await apiFetch(`/api/v1/contacts/${contactId}`, { method: 'DELETE' });
    await loadData();
    showToast('Contato excluído.');
  } catch {
    showToast('Não foi possível excluir o contato.');
  }
}

function bindEvents() {
  $$('[data-section]').forEach((item) => item.addEventListener('click', () => navigate(item.dataset.section)));
  $('#refresh-button').addEventListener('click', refresh);
  $('#hero-refresh').addEventListener('click', refresh);
  ['contacts-refresh', 'templates-refresh', 'campaigns-refresh'].forEach((id) => $(`#${id}`).addEventListener('click', refresh));
  $('#toggle-contact-form').addEventListener('click', () => openContactForm());
  $('#close-contact-form').addEventListener('click', closeContactForm);
  $('#contact-form').addEventListener('submit', submitContacts);
  $('#contacts-table-body').addEventListener('click', (event) => {
    const editButton = event.target.closest('[data-edit-contact]');
    const deleteButton = event.target.closest('[data-delete-contact]');
    if (editButton) openContactForm(state.contacts.find((contact) => contact.id === Number(editButton.dataset.editContact)));
    if (deleteButton) deleteContact(Number(deleteButton.dataset.deleteContact));
  });
  $('#new-campaign-button').addEventListener('click', () => openCampaignPlanner());
  $('#close-campaign-planner').addEventListener('click', closeCampaignPlanner);
  $('#campaign-form').addEventListener('submit', (event) => { event.preventDefault(); saveCampaign(); });
  $('#send-campaign-button').addEventListener('click', () => saveCampaign({ send: true }));
  $('#campaign-attachment').addEventListener('change', () => {
    const file = $('#campaign-attachment').files[0];
    $('#campaign-attachment-help').textContent = file
      ? `${file.name} · ${Math.ceil(file.size / 1024)} KB · será enviado junto com a campanha.`
      : 'Qualquer tipo de arquivo, até 25 MB. O anexo será enviado junto com a campanha.';
  });
  $('#delete-campaign-button').addEventListener('click', deleteCampaign);
  $('#recipient-search').addEventListener('input', renderRecipientPicker);
  $('#recipient-list').addEventListener('change', (event) => {
    const input = event.target.closest('[data-recipient-id]');
    if (!input) return;
    const contactId = Number(input.dataset.recipientId);
    state.planner.selectedContactIds = input.checked
      ? [...new Set([...state.planner.selectedContactIds, contactId])]
      : state.planner.selectedContactIds.filter((id) => id !== contactId);
    renderRecipientPicker();
  });
  $('#select-all-recipients').addEventListener('click', () => {
    const query = $('#recipient-search').value.trim().toLowerCase();
    const visibleIds = state.contacts.filter((contact) => {
      const haystack = `${contact.email} ${contact.display_name || ''} ${contact.organization || ''}`.toLowerCase();
      return contact.status === 'active' && (!query || haystack.includes(query));
    }).map((contact) => contact.id);
    state.planner.selectedContactIds = [...new Set([...state.planner.selectedContactIds, ...visibleIds])];
    renderRecipientPicker();
  });
  $('#clear-recipients').addEventListener('click', () => {
    state.planner.selectedContactIds = [];
    renderRecipientPicker();
  });
  $('#save-token').addEventListener('click', async () => {
    const token = $('#api-token').value.trim();
    if (!token) {
      localStorage.removeItem('email-automation-api-token');
      $('#token-feedback').textContent = 'Token removido deste navegador.';
      showToast('Token removido.');
    } else {
      localStorage.setItem('email-automation-api-token', token);
      $('#token-feedback').textContent = 'Token salvo somente neste navegador.';
      showToast('Token salvo. Carregando dados…');
    }
    await refresh();
  });
  const campaignAction = (event) => {
    const editButton = event.target.closest('[data-edit-campaign]');
    const deleteButton = event.target.closest('[data-delete-campaign]');
    const openButton = event.target.closest('[data-campaign-id]');
    if (editButton) openCampaignPlanner(state.campaigns.find((campaign) => campaign.id === Number(editButton.dataset.editCampaign)));
    else if (deleteButton) {
      const campaign = state.campaigns.find((item) => item.id === Number(deleteButton.dataset.deleteCampaign));
      if (campaign) {
        state.planner.campaignId = campaign.id;
        deleteCampaign();
      }
    } else if (openButton) {
      navigate('campaigns');
      const campaign = state.campaigns.find((item) => item.id === Number(openButton.dataset.campaignId));
      if (campaign?.status === 'draft') openCampaignPlanner(campaign);
    }
  };
  $('#campaigns-table-body').addEventListener('click', campaignAction);
  $('#campaign-cards').addEventListener('click', campaignAction);
}

async function boot() {
  $('#api-token').value = getToken();
  bindEvents();
  renderAll();
  await refresh();
}

document.addEventListener('DOMContentLoaded', boot);

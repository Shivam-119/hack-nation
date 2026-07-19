async function request(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json().catch(() => null);
  if (!response.ok || data?.error) throw new Error(data?.detail || data?.error || `${response.status} ${response.statusText}`);
  return data;
}

export const api = {
  thesis: () => request('/api/thesis'),
  saveThesis: (body) => request('/api/thesis', { method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) }),
  applications: () => request('/api/applications'),
  application: (id) => request(`/api/applications/${id}`),
  submit: (data) => request('/api/applications', { method: 'POST', body: data }),
  evaluation: (id) => request(`/api/applications/${id}/evaluation`),
  queueEvaluation: (id) => request(`/api/applications/${id}/evaluation`, { method: 'POST' }),
  deckUrl: (id) => `/api/applications/${id}/deck`,
};

// Get CSRF token from cookie
function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(';').shift();
}

// API base URL
const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:7123';

// Wrapper for fetch with CSRF token
export async function apiRequest(endpoint, options = {}) {
  const csrfToken = getCookie('csrftoken');
  
  const defaultOptions = {
    credentials: 'include', // Important: sends cookies
    headers: {
      'Content-Type': 'application/json',
      ...(csrfToken && { 'X-CSRFToken': csrfToken }),
      ...options.headers,
    },
  };

  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...defaultOptions,
    ...options,
  });

  if (!response.ok) {
    throw new Error(`API Error: ${response.status}`);
  }

  return response.json();
}
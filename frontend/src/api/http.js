import axios from 'axios';

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

export const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const detail = error?.response?.data?.detail;
    const message =
      typeof detail === 'string'
        ? detail
        : error?.response?.data?.message || error.message || 'Request failed';

    error.userMessage = message;
    return Promise.reject(error);
  },
);

export const API_BASE_URL = 'https://salmanloyalty.replit.app';

export const endpoints = {
  login: '/api/mobile/login',
  customerLookup: '/api/pos/customer-lookup',
  punchCards: (customerId: number) => `/api/punch-cards/customer/${customerId}`,
  transactions: (customerId: number) => `/api/loyalty/customer/${customerId}/transactions`,
  profile: (customerId: number) => `/api/customers/${customerId}`,
};

export async function apiRequest<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`;
  
  const response = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: 'Request failed' }));
    throw new Error(error.error || 'Request failed');
  }

  return response.json();
}

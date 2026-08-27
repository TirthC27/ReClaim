/**
 * API client for the Project Flow backend.
 */

const API_BASE = "http://localhost:8000";

async function request(path, options = {}) {
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });

  if (!res.ok) {
    const errorBody = await res.json().catch(() => ({}));
    throw new Error(errorBody.detail || `API error: ${res.status}`);
  }

  return res.json();
}

// ── Shopify ────────────────────────────────────────────────
export const fetchVendors = () => request("/shopify/vendors");

// ── Merchants ──────────────────────────────────────────────
export const onboardMerchant = (data) =>
  request("/merchants/onboard", {
    method: "POST",
    body: JSON.stringify(data),
  });

export const fetchShopifyProducts = (merchantId) =>
  request(`/merchants/${merchantId}/shopify-products`);

export const linkProducts = (merchantId, assignments) =>
  request(`/merchants/${merchantId}/link-products`, {
    method: "POST",
    body: JSON.stringify({ assignments }),
  });

// ── Documents ──────────────────────────────────────────────
export const uploadDocument = async (merchantId, file) => {
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(`${API_BASE}/merchants/${merchantId}/documents`, {
    method: "POST",
    body: formData,
    // No Content-Type header — browser sets multipart boundary automatically
  });

  if (!res.ok) {
    const errorBody = await res.json().catch(() => ({}));
    throw new Error(errorBody.detail || `Upload error: ${res.status}`);
  }

  return res.json();
};

export const fetchDocuments = (merchantId) =>
  request(`/merchants/${merchantId}/documents`);

// ── Product Groups ─────────────────────────────────────────
export const fetchProductGroups = () => request("/product-groups");

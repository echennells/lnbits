/**
 * API functions for Taproot Assets extension
 */

// Get settings for the Taproot Assets extension
function getSettings(adminkey) {
  return LNbits.api
    .request('GET', '/taproot_assets/api/v1/taproot/settings', adminkey);
}

// Save settings for the Taproot Assets extension
function saveSettings(adminkey, settings) {
  return LNbits.api
    .request('PUT', '/taproot_assets/api/v1/taproot/settings', adminkey, settings);
}

// Get list of assets from the Taproot Assets daemon
function getAssets(adminkey) {
  return LNbits.api
    .request('GET', '/taproot_assets/api/v1/taproot/listassets', adminkey);
}

// Get invoices for the Taproot Assets extension
function getInvoices(adminkey, cache = true) {
  const timestamp = cache ? new Date().getTime() : null;
  const url = `/taproot_assets/api/v1/taproot/invoices${timestamp ? `?_=${timestamp}` : ''}`;
  
  return LNbits.api
    .request('GET', url, adminkey);
}

// Get payments for the Taproot Assets extension
function getPayments(adminkey, cache = true) {
  const timestamp = cache ? new Date().getTime() : null;
  const url = `/taproot_assets/api/v1/taproot/payments${timestamp ? `?_=${timestamp}` : ''}`;
  
  return LNbits.api
    .request('GET', url, adminkey);
}

// Create an invoice for a Taproot Asset
function createInvoice(adminkey, payload) {
  return LNbits.api
    .request('POST', '/taproot_assets/api/v1/taproot/invoice', adminkey, payload);
}

// Pay a Taproot Asset invoice
function payInvoice(adminkey, payload) {
  return LNbits.api
    .request('POST', '/taproot_assets/api/v1/taproot/pay', adminkey, payload);
}

// Explicitly process a self-payment (direct endpoint)
function processSelfPayment(adminkey, payload) {
  return LNbits.api
    .request('POST', '/taproot_assets/api/v1/taproot/self-payment', adminkey, payload);
}

// Parse an invoice using the server-side endpoint
function parseInvoice(adminkey, paymentRequest) {
  return LNbits.api
    .request('GET', `/taproot_assets/api/v1/taproot/parse-invoice?payment_request=${encodeURIComponent(paymentRequest)}`, adminkey);
}

// Get asset balances
function getAssetBalances(adminkey) {
  return LNbits.api
    .request('GET', '/taproot_assets/api/v1/taproot/asset-balances', adminkey);
}

// Get balance for a specific asset
function getAssetBalance(adminkey, assetId) {
  return LNbits.api
    .request('GET', `/taproot_assets/api/v1/taproot/asset-balance/${encodeURIComponent(assetId)}`, adminkey);
}

// Get asset transactions
function getAssetTransactions(adminkey, assetId = null, limit = 100) {
  let url = '/taproot_assets/api/v1/taproot/asset-transactions';
  const params = [];
  
  if (assetId) {
    params.push(`asset_id=${encodeURIComponent(assetId)}`);
  }
  
  if (limit) {
    params.push(`limit=${limit}`);
  }
  
  if (params.length > 0) {
    url += `?${params.join('&')}`;
  }
  
  return LNbits.api
    .request('GET', url, adminkey);
}

// Update invoice status
function updateInvoiceStatus(adminkey, invoiceId, status) {
  return LNbits.api
    .request('PUT', `/taproot_assets/api/v1/taproot/invoices/${invoiceId}/status?status=${status}`, adminkey);
}

/**
 * API Service for Taproot Assets extension
 * Centralizes all API calls to the backend
 */

const ApiService = {
  /**
   * Get list of assets from the Taproot Assets daemon
   * @param {string} adminkey - Admin key for authentication
   * @returns {Promise} - Promise that resolves with assets data
   */
  getAssets(adminkey) {
    return LNbits.api
      .request('GET', '/taproot_assets/api/v1/taproot/listassets', adminkey)
      .catch(error => {
        console.error('API Error getting assets:', error);
        throw error;
      });
  },

  /**
   * Get invoices for the Taproot Assets extension
   * @param {string} adminkey - Admin key for authentication
   * @param {boolean} cache - Whether to use cache-busting timestamp 
   * @returns {Promise} - Promise that resolves with invoices data
   */
  getInvoices(adminkey, cache = true) {
    const timestamp = cache ? new Date().getTime() : null;
    const url = `/taproot_assets/api/v1/taproot/invoices${timestamp ? `?_=${timestamp}` : ''}`;
    
    return LNbits.api
      .request('GET', url, adminkey)
      .catch(error => {
        console.error('API Error getting invoices:', error);
        throw error;
      });
  },

  /**
   * Get payments for the Taproot Assets extension
   * @param {string} adminkey - Admin key for authentication
   * @param {boolean} cache - Whether to use cache-busting timestamp
   * @returns {Promise} - Promise that resolves with payments data
   */
  getPayments(adminkey, cache = true) {
    const timestamp = cache ? new Date().getTime() : null;
    const url = `/taproot_assets/api/v1/taproot/payments${timestamp ? `?_=${timestamp}` : ''}`;
    
    return LNbits.api
      .request('GET', url, adminkey)
      .catch(error => {
        console.error('API Error getting payments:', error);
        throw error;
      });
  },

  /**
   * Create an invoice for a Taproot Asset
   * @param {string} adminkey - Admin key for authentication
   * @param {Object} payload - Invoice creation payload
   * @returns {Promise} - Promise that resolves with created invoice data
   */
  createInvoice(adminkey, payload) {
    return LNbits.api
      .request('POST', '/taproot_assets/api/v1/taproot/invoice', adminkey, payload)
      .catch(error => {
        console.error('API Error creating invoice:', error);
        throw error;
      });
  },

  /**
   * Pay a Taproot Asset invoice
   * @param {string} adminkey - Admin key for authentication
   * @param {Object} payload - Payment payload
   * @returns {Promise} - Promise that resolves with payment result
   */
  payInvoice(adminkey, payload) {
    return LNbits.api
      .request('POST', '/taproot_assets/api/v1/taproot/pay', adminkey, payload)
      .catch(error => {
        console.error('API Error paying invoice:', error);
        throw error;
      });
  },


  /**
   * Parse an invoice using the server-side endpoint
   * @param {string} adminkey - Admin key for authentication
   * @param {string} paymentRequest - Payment request to parse
   * @returns {Promise} - Promise that resolves with parsed invoice data
   */
  parseInvoice(adminkey, paymentRequest) {
    return LNbits.api
      .request('GET', `/taproot_assets/api/v1/taproot/parse-invoice?payment_request=${encodeURIComponent(paymentRequest)}`, adminkey)
      .catch(error => {
        console.error('API Error parsing invoice:', error);
        throw error;
      });
  },

  /**
   * Get asset balances
   * @param {string} adminkey - Admin key for authentication
   * @returns {Promise} - Promise that resolves with asset balances
   */
  getAssetBalances(adminkey) {
    return LNbits.api
      .request('GET', '/taproot_assets/api/v1/taproot/asset-balances', adminkey)
      .catch(error => {
        console.error('API Error getting asset balances:', error);
        throw error;
      });
  }

  // Removed unused functions: getAssetBalance and getAssetTransactions
};

// Export the service
window.ApiService = ApiService;

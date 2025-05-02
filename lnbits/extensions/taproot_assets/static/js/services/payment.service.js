/**
 * Payments Service for Taproot Assets extension
 * Handles payment processing, fetching, and management
 */

const PaymentService = {
  /**
   * Get all payments for the current user
   * @param {Object} wallet - Wallet object with adminkey
   * @param {boolean} forceFresh - Whether to force fresh data from server
   * @returns {Promise<Array>} - Promise that resolves with payments
   */
  async getPayments(wallet, cache = true) {
    try {
      if (!wallet || !wallet.adminkey) {
        throw new Error('Valid wallet is required');
      }
      
      // Use timestamp for cache busting if needed
      const timestamp = cache ? new Date().getTime() : null;
      const url = `/taproot_assets/api/v1/taproot/payments${timestamp ? `?_=${timestamp}` : ''}`;
      
      // Request payments from the API
      const response = await LNbits.api.request('GET', url, wallet.adminkey);
      
      if (!response || !response.data) {
        return [];
      }
      
      // Process the payments
      const payments = Array.isArray(response.data)
        ? response.data.map(payment => this._mapPayment(payment))
        : [];
      
      return payments;
    } catch (error) {
      console.error('Failed to fetch payments:', error);
      throw error;
    }
  },
  
  /**
   * Parse an invoice to get payment details
   * @param {Object} wallet - Wallet object with adminkey
   * @param {string} paymentRequest - Payment request to parse
   * @returns {Promise<Object>} - Promise with parsed invoice
   */
  async parseInvoice(wallet, paymentRequest) {
    try {
      if (!wallet || !wallet.adminkey) {
        throw new Error('Valid wallet is required');
      }
      
      if (!paymentRequest || paymentRequest.trim() === '') {
        throw new Error('Payment request is required');
      }
      
      // Request parsing from the API
      const response = await LNbits.api.request(
        'GET', 
        `/taproot_assets/api/v1/taproot/parse-invoice?payment_request=${encodeURIComponent(paymentRequest)}`, 
        wallet.adminkey
      );
      
      if (!response || !response.data) {
        throw new Error('Failed to parse invoice: No data returned');
      }
      
      return response.data;
    } catch (error) {
      console.error('Failed to parse invoice:', error);
      throw error;
    }
  },
  
  /**
   * Pay a Taproot Asset invoice
   * @param {Object} wallet - Wallet object with adminkey
   * @param {Object} assetData - Asset data for payment
   * @param {Object} paymentData - Payment data (request, fee limit, etc)
   * @returns {Promise<Object>} - Promise with payment result
   */
  async payInvoice(wallet, assetData, paymentData) {
    try {
      if (!wallet || !wallet.adminkey) {
        throw new Error('Valid wallet is required');
      }
      
      if (!paymentData || !paymentData.paymentRequest) {
        throw new Error('Payment request is required');
      }
      
      // Create payload
      const payload = {
        payment_request: paymentData.paymentRequest,
        fee_limit_sats: paymentData.feeLimit || 1000
      };
      
      // Add peer_pubkey if available
      if (assetData && assetData.channel_info && assetData.channel_info.peer_pubkey) {
        payload.peer_pubkey = assetData.channel_info.peer_pubkey;
      }
      
      // Make the payment request
      const response = await LNbits.api.request(
        'POST', 
        '/taproot_assets/api/v1/taproot/pay', 
        wallet.adminkey, 
        payload
      );
      
      if (!response || !response.data) {
        throw new Error('Failed to process payment: No data returned');
      }
      
      return response.data;
    } catch (error) {
      // Check for special cases that might need handling
      if (error.response && 
          error.response.data && 
          error.response.data.detail && 
          (error.response.data.detail.includes('internal payment') || 
           error.response.data.detail.includes('own invoice'))) {
        // This is likely an internal payment that should be routed differently
        throw {
          ...error,
          isInternalPayment: true,
          message: 'This invoice belongs to another user on this node. System will process it as an internal payment.'
        };
      }
      
      console.error('Failed to pay invoice:', error);
      throw error;
    }
  },
  
  /**
   * Process an internal payment (between users on the same node)
   * @param {Object} wallet - Wallet object with adminkey
   * @param {Object} paymentData - Payment data
   * @returns {Promise<Object>} - Promise with payment result
   */
  async processInternalPayment(wallet, paymentData) {
    try {
      if (!wallet || !wallet.adminkey) {
        throw new Error('Valid wallet is required');
      }
      
      if (!paymentData || !paymentData.paymentRequest) {
        throw new Error('Payment request is required');
      }
      
      // Create payload
      const payload = {
        payment_request: paymentData.paymentRequest,
        fee_limit_sats: paymentData.feeLimit || 10
      };
      
      // Call the internal payment endpoint
      const response = await LNbits.api.request(
        'POST', 
        '/taproot_assets/api/v1/taproot/internal-payment', 
        wallet.adminkey, 
        payload
      );
      
      if (!response || !response.data) {
        throw new Error('Failed to process internal payment: No data returned');
      }
      
      return response.data;
    } catch (error) {
      console.error('Failed to process internal payment:', error);
      throw error;
    }
  },
  
  /**
   * Process a self-payment (deprecated but maintained for compatibility)
   * @param {Object} wallet - Wallet object with adminkey
   * @param {Object} paymentData - Payment data
   * @returns {Promise<Object>} - Promise with payment result
   */
  async processSelfPayment(wallet, paymentData) {
    try {
      if (!wallet || !wallet.adminkey) {
        throw new Error('Valid wallet is required');
      }
      
      if (!paymentData || !paymentData.paymentRequest) {
        throw new Error('Payment request is required');
      }
      
      // Create payload
      const payload = {
        payment_request: paymentData.paymentRequest,
        fee_limit_sats: paymentData.feeLimit || 10
      };
      
      // Call the self-payment endpoint
      const response = await LNbits.api.request(
        'POST', 
        '/taproot_assets/api/v1/taproot/self-payment', 
        wallet.adminkey, 
        payload
      );
      
      if (!response || !response.data) {
        throw new Error('Failed to process self-payment: No data returned');
      }
      
      return response.data;
    } catch (error) {
      console.error('Failed to process self-payment:', error);
      throw error;
    }
  },
  
  /**
   * Process and transform a payment object
   * @param {Object} payment - Raw payment data
   * @returns {Object} - Processed payment
   */
  _mapPayment(payment) {
    if (!payment) return null;
    
    // Create a clean copy
    const mapped = {...payment};
    
    // Set type and direction
    mapped.type = 'payment';
    mapped.direction = 'outgoing';
    
    // Format date consistently
    if (mapped.created_at) {
      try {
        const date = new Date(mapped.created_at);
        // Format exactly like LNbits: YYYY-MM-DD HH:MM:SS
        if (window.Quasar && window.Quasar.date) {
          mapped.date = window.Quasar.date.formatDate(date, 'YYYY-MM-DD HH:mm:ss');
        } else {
          mapped.date = date.toISOString().replace('T', ' ').slice(0, 19);
        }
        
        // Calculate "timeFrom" like LNbits
        const now = new Date();
        const diffMs = now - date;
        
        if (diffMs < 60000) { // less than a minute
          mapped.timeFrom = 'a minute ago';
        } else if (diffMs < 3600000) { // less than an hour
          const mins = Math.floor(diffMs / 60000);
          mapped.timeFrom = `${mins} minute${mins > 1 ? 's' : ''} ago`;
        } else if (diffMs < 86400000) { // less than a day
          const hours = Math.floor(diffMs / 3600000);
          mapped.timeFrom = `${hours} hour${hours > 1 ? 's' : ''} ago`;
        } else if (diffMs < 604800000) { // less than a week
          const days = Math.floor(diffMs / 86400000);
          mapped.timeFrom = `${days} day${days > 1 ? 's' : ''} ago`;
        } else {
          // Just use date for older items
          mapped.timeFrom = mapped.date;
        }
      } catch (e) {
        console.error('Error formatting date:', e, mapped.created_at);
        mapped.date = 'Unknown';
        mapped.timeFrom = 'Unknown';
      }
    }
    
    // Ensure extra exists and contains asset info
    mapped.extra = mapped.extra || {};
    
    mapped.extra = {
      asset_amount: mapped.asset_amount,
      asset_id: mapped.asset_id,
      fee_sats: mapped.fee_sats
    };
    
    return mapped;
  }
};

// Export the service
window.PaymentService = PaymentService;

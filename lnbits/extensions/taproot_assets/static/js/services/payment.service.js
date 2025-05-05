/**
 * Payments Service for Taproot Assets extension
 * Handles payment processing, fetching, and management
 */

const PaymentService = {
  /**
   * Get all payments for the current user
   * @param {Object} wallet - Wallet object with adminkey
   * @param {boolean} cache - Whether to use cache-busting timestamp 
   * @returns {Promise<Array>} - Promise that resolves with payments
   */
  async getPayments(wallet, cache = true) {
    try {
      if (!wallet || !wallet.adminkey) {
        throw new Error('Valid wallet is required');
      }
      
      // Set loading state in store if available
      if (window.taprootStore && window.taprootStore.actions) {
        window.taprootStore.actions.setTransactionsLoading(true);
      }
      
      // Update current wallet in store if available
      if (window.taprootStore && window.taprootStore.actions) {
        window.taprootStore.actions.setCurrentWallet(wallet);
      }
      
      // Request payments from the API
      const response = await ApiService.getPayments(wallet.adminkey, cache);
      
      if (!response || !response.data) {
        // Update store if available
        if (window.taprootStore && window.taprootStore.actions) {
          window.taprootStore.actions.setPayments([]);
        }
        return [];
      }
      
      // Process the payments
      const payments = Array.isArray(response.data)
        ? response.data.map(payment => this._mapPayment(payment))
        : [];
      
      // Update the store if available
      if (window.taprootStore && window.taprootStore.actions) {
        window.taprootStore.actions.setPayments(payments);
      }
      
      return payments;
    } catch (error) {
      console.error('Failed to fetch payments:', error);
      throw error;
    } finally {
      // Ensure loading state is reset
      if (window.taprootStore && window.taprootStore.actions) {
        window.taprootStore.actions.setTransactionsLoading(false);
      }
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
      const response = await ApiService.parseInvoice(wallet.adminkey, paymentRequest);
      
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
      const response = await ApiService.payInvoice(wallet.adminkey, payload);
      
      if (!response || !response.data) {
        throw new Error('Failed to process payment: No data returned');
      }
      
      // Update asset information in the store with new balance
      if (response.data.asset_id && assetData && window.taprootStore && window.taprootStore.actions) {
        // Deduct the asset amount from the user's balance
        const newBalance = (assetData.user_balance || 0) - response.data.asset_amount;
        
        // Update the asset in the store
        window.taprootStore.actions.updateAsset(assetData.asset_id, { 
          user_balance: Math.max(0, newBalance) 
        });
      }
      
      // Create payment record for store
      const payment = {
        id: response.data.payment_hash || Date.now().toString(),
        payment_hash: response.data.payment_hash,
        payment_request: paymentData.paymentRequest,
        asset_id: response.data.asset_id || assetData.asset_id,
        asset_amount: response.data.asset_amount,
        fee_sats: response.data.fee_msat ? Math.ceil(response.data.fee_msat / 1000) : 0,
        memo: assetData.name ? `Sent ${response.data.asset_amount} ${assetData.name}` : 'Asset payment',
        status: 'completed',
        user_id: wallet.user,
        wallet_id: wallet.id,
        created_at: new Date().toISOString(),
        preimage: response.data.preimage
      };
      
      // Add mapped payment to store if available
      const mappedPayment = this._mapPayment(payment);
      if (window.taprootStore && window.taprootStore.actions) {
        window.taprootStore.actions.addPayment(mappedPayment);
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
      const response = await ApiService.processInternalPayment(wallet.adminkey, payload);
      
      if (!response || !response.data) {
        throw new Error('Failed to process internal payment: No data returned');
      }
      
      // Find the asset in the store
      let asset = null;
      if (window.taprootStore && window.taprootStore.state && window.taprootStore.state.assets) {
        asset = window.taprootStore.state.assets.find(a => a.asset_id === response.data.asset_id);
      }
      
      // Update asset information in the store if found
      if (response.data.asset_id && asset && window.taprootStore && window.taprootStore.actions) {
        // Deduct the asset amount from the user's balance
        const newBalance = (asset.user_balance || 0) - response.data.asset_amount;
        
        // Update the asset in the store
        window.taprootStore.actions.updateAsset(asset.asset_id, { 
          user_balance: Math.max(0, newBalance) 
        });
      }
      
      // Create payment record for store
      const payment = {
        id: response.data.payment_hash || Date.now().toString(),
        payment_hash: response.data.payment_hash,
        payment_request: paymentData.paymentRequest,
        asset_id: response.data.asset_id,
        asset_amount: response.data.asset_amount,
        fee_sats: 0, // Internal payments have zero fee
        memo: asset ? `Sent ${response.data.asset_amount} ${asset.name} (Internal)` : 'Internal asset payment',
        status: 'completed',
        user_id: wallet.user,
        wallet_id: wallet.id,
        created_at: new Date().toISOString(),
        preimage: response.data.preimage,
        internal_payment: true
      };
      
      // Add mapped payment to store
      const mappedPayment = this._mapPayment(payment);
      if (window.taprootStore && window.taprootStore.actions) {
        window.taprootStore.actions.addPayment(mappedPayment);
      }
      
      return response.data;
    } catch (error) {
      console.error('Failed to process internal payment:', error);
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
  },
  
  /**
   * Process WebSocket payment update
   * @param {Object} data - Payment data from WebSocket
   */
  processWebSocketUpdate(data) {
    if (data && data.type === 'payment_update' && data.data) {
      // Map the payment
      const payment = this._mapPayment(data.data);
      
      // Add to store if available
      if (window.taprootStore && window.taprootStore.actions) {
        window.taprootStore.actions.addPayment(payment);
      }
      
      // Return the processed payment
      return payment;
    }
    return null;
  }
};

// Export the service
window.PaymentService = PaymentService;

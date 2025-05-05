/**
 * Invoice Service for Taproot Assets extension
 * Handles invoice creation, fetching, and management
 */

const InvoiceService = {
  /**
   * Get all invoices for the current user
   * @param {Object} wallet - Wallet object with adminkey
   * @param {boolean} forceFresh - Whether to force fresh data from server
   * @returns {Promise<Array>} - Promise that resolves with invoices
   */
  async getInvoices(wallet, forceFresh = false) {
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
      
      // Request invoices from the API
      const timestamp = new Date().getTime();
      const response = await ApiService.getInvoices(wallet.adminkey, true);
      
      if (!response || !response.data) {
        // Update store if available
        if (window.taprootStore && window.taprootStore.actions) {
          window.taprootStore.actions.setInvoices([]);
        }
        return [];
      }
      
      // Process the invoices
      const invoices = Array.isArray(response.data)
        ? response.data.map(invoice => this._mapInvoice(invoice))
        : [];
      
      // Update the store if available
      if (window.taprootStore && window.taprootStore.actions) {
        window.taprootStore.actions.setInvoices(invoices);
      }
      
      return invoices;
    } catch (error) {
      console.error('Failed to fetch invoices:', error);
      throw error;
    } finally {
      // Ensure loading state is reset
      if (window.taprootStore && window.taprootStore.actions) {
        window.taprootStore.actions.setTransactionsLoading(false);
      }
    }
  },
  
  /**
   * Create a new invoice for a Taproot Asset
   * @param {Object} wallet - Wallet object with adminkey
   * @param {Object} assetData - Asset data and channel information
   * @param {Object} invoiceData - Invoice creation data
   * @returns {Promise<Object>} - Promise with created invoice
   */
  async createInvoice(wallet, assetData, invoiceData) {
    try {
      if (!wallet || !wallet.adminkey) {
        throw new Error('Valid wallet is required');
      }
      
      if (!assetData || !assetData.asset_id) {
        throw new Error('Valid asset data is required');
      }
      
      // Create payload from asset data and form data
      const payload = {
        asset_id: assetData.asset_id,
        amount: parseFloat(invoiceData.amount),
        memo: invoiceData.memo || '',
        expiry: invoiceData.expiry || 3600
      };
      
      // Add peer_pubkey if available in channel info
      if (assetData.channel_info && assetData.channel_info.peer_pubkey) {
        payload.peer_pubkey = assetData.channel_info.peer_pubkey;
      }
      
      // Request creation from the API
      const response = await ApiService.createInvoice(wallet.adminkey, payload);
      
      if (!response || !response.data) {
        throw new Error('Failed to create invoice: No data returned');
      }
      
      // Process and return the invoice
      const createdInvoice = response.data;
      
      // Add asset name to the created invoice for better UX
      createdInvoice.asset_name = assetData.name || 'Unknown';
      
      // Process invoice for store
      const mappedInvoice = this._mapInvoice(createdInvoice);
      
      // Add to store if available
      if (window.taprootStore && window.taprootStore.actions) {
        window.taprootStore.actions.addInvoice(mappedInvoice);
      }
      
      return createdInvoice;
    } catch (error) {
      console.error('Failed to create invoice:', error);
      throw error;
    }
  },
  
  /**
   * Process and transform an invoice object
   * @param {Object} invoice - Raw invoice data
   * @returns {Object} - Processed invoice
   * @private
   */
  _mapInvoice(invoice) {
    if (!invoice) return null;
    
    // Create a clean copy
    const mapped = {...invoice};
    
    // Set type and direction
    mapped.type = 'invoice';
    mapped.direction = 'incoming';
    
    // Format date consistently
    if (mapped.created_at) {
      try {
        const date = new Date(mapped.created_at);
        // Format exactly like LNbits: YYYY-MM-DD HH:MM:SS
        if (window.Quasar && window.Quasar.date && window.Quasar.date.formatDate) {
          mapped.date = window.Quasar.date.formatDate(date, 'YYYY-MM-DD HH:mm:ss');
        } else {
          mapped.date = date.toISOString().replace('T', ' ').substring(0, 19);
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
    
    if (!mapped.extra.asset_amount && mapped.asset_amount) {
      mapped.extra.asset_amount = mapped.asset_amount;
    }
    
    if (!mapped.extra.asset_id && mapped.asset_id) {
      mapped.extra.asset_id = mapped.asset_id;
    }
    
    return mapped;
  },
  
  /**
   * Process WebSocket invoice update
   * @param {Object} data - Invoice data from WebSocket
   */
  processWebSocketUpdate(data) {
    if (data && data.type === 'invoice_update' && data.data) {
      // Map the invoice
      const invoice = this._mapInvoice(data.data);
      
      // Add to store if available
      if (window.taprootStore && window.taprootStore.actions) {
        window.taprootStore.actions.addInvoice(invoice);
      }
      
      // Return the processed invoice
      return invoice;
    }
    return null;
  },
  
  /**
   * Process a paid invoice and update state
   * @param {Object} invoice - The paid invoice
   * @returns {Object} - Information about the processed invoice
   */
  processPaidInvoice(invoice) {
    if (!invoice) return null;
    
    // Update the store if available
    if (invoice.id && window.taprootStore && window.taprootStore.actions) {
      window.taprootStore.actions.updateInvoice(invoice.id, { 
        status: 'paid',
        paid_at: new Date().toISOString()
      });
    }
    
    // Return information for UI notifications
    return {
      assetName: AssetService.getAssetName(invoice.asset_id),
      amount: invoice.asset_amount || 0,
      paymentHash: invoice.payment_hash,
      invoiceId: invoice.id
    };
  }
};

// Export the service
window.InvoiceService = InvoiceService;

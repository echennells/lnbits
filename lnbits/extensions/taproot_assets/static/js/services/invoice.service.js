/**
 * Invoice Service for Taproot Assets extension
 * Simplified and optimized to work with the WebSocket manager
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
      
      // Set loading state
      window.taprootStore.actions.setTransactionsLoading(true);
      window.taprootStore.actions.setCurrentWallet(wallet);
      
      // Request invoices from the API
      const response = await ApiService.getInvoices(wallet.adminkey, forceFresh);
      
      // Process the invoices
      const invoices = Array.isArray(response?.data)
        ? response.data.map(invoice => this._mapInvoice(invoice))
        : [];
      
      // Update the store with processed invoices
      window.taprootStore.actions.setInvoices(invoices);
      
      return invoices;
    } catch (error) {
      console.error('Failed to fetch invoices:', error);
      window.taprootStore.actions.setInvoices([]);
      return [];
    } finally {
      // Ensure loading state is reset
      window.taprootStore.actions.setTransactionsLoading(false);
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
      if (assetData.channel_info?.peer_pubkey) {
        payload.peer_pubkey = assetData.channel_info.peer_pubkey;
      }
      
      // Request creation from the API
      const response = await ApiService.createInvoice(wallet.adminkey, payload);
      
      if (!response?.data) {
        throw new Error('Failed to create invoice: No data returned');
      }
      
      // Process the invoice
      const createdInvoice = response.data;
      
      // Add asset name to the created invoice for better UX
      createdInvoice.asset_name = assetData.name || 'Unknown';
      
      // Process invoice for store
      const mappedInvoice = this._mapInvoice(createdInvoice);
      
      // Add to store
      window.taprootStore.actions.addInvoice(mappedInvoice);
      
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
    
    // Format date using DataUtils
    if (mapped.created_at) {
      try {
        mapped.date = DataUtils.formatDate(mapped.created_at);
        mapped.timeFrom = DataUtils.getRelativeTime(mapped.created_at);
      } catch (e) {
        console.error('Error formatting date:', e);
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
   * @returns {Object|null} - Processed invoice or null
   */
  processWebSocketUpdate(data) {
    if (!data?.type || data.type !== 'invoice_update' || !data.data) {
      return null;
    }
    
    // Map the invoice
    const invoice = this._mapInvoice(data.data);
    
    // Add to store
    if (invoice) {
      window.taprootStore.actions.addInvoice(invoice);
    }
    
    return invoice;
  },
  
  /**
   * Process a paid invoice and update state
   * @param {Object} invoice - The paid invoice
   * @returns {Object|null} - Information about the processed invoice or null
   */
  processPaidInvoice(invoice) {
    if (!invoice) return null;
    
    // Update invoice in store
    if (invoice.id) {
      window.taprootStore.actions.updateInvoice(invoice.id, { 
        status: 'paid',
        paid_at: new Date().toISOString()
      });
    }
    
    // Return information for UI notifications
    return {
      assetName: window.AssetService?.getAssetName(invoice.asset_id) || 'Unknown Asset',
      amount: invoice.asset_amount || 0,
      paymentHash: invoice.payment_hash,
      invoiceId: invoice.id
    };
  },
  
  /**
   * Get an invoice by ID
   * @param {string} invoiceId - ID of the invoice to find
   * @returns {Object|null} - Invoice object or null if not found
   */
  getInvoiceById(invoiceId) {
    if (!invoiceId || !window.taprootStore?.state?.invoices) {
      return null;
    }
    
    return window.taprootStore.state.invoices.find(inv => inv.id === invoiceId) || null;
  },
  
  /**
   * Check if an invoice is paid
   * @param {string} invoiceId - ID of the invoice to check
   * @returns {boolean} - Whether the invoice is paid
   */
  isInvoicePaid(invoiceId) {
    const invoice = this.getInvoiceById(invoiceId);
    return invoice ? invoice.status === 'paid' : false;
  }
};

// Export the service
window.InvoiceService = InvoiceService;

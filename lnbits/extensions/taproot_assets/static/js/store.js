/**
 * Centralized state management for Taproot Assets extension
 * Uses Vue.js reactivity system
 */

// Create reactive state store
const taprootStore = {
  // State - reactive data store
  state: Vue.reactive({
    // Assets
    assets: [],
    assetsLoading: false,
    
    // Transactions
    invoices: [],
    payments: [],
    transactionsLoading: false,
    
    // Filters and search
    filters: {
      direction: 'all',
      status: 'all',
      searchText: '',
      dateFrom: null,
      dateTo: null
    },
    
    // WebSocket status
    websocketStatus: {
      connected: false,
      reconnecting: false,
      fallbackPolling: false
    },
    
    // Current user wallet
    currentWallet: null,
    
    // WebSocket status only
  }),
  
  // Computed properties
  getters: {
    // Filtered assets with channel information
    filteredAssets() {
      // Check if state is defined
      if (!this.state || !this.state.assets || this.state.assets.length === 0) {
        return [];
      }
      
      return this.state.assets
        .filter(asset => asset.channel_info !== undefined)
        .map(asset => {
          // Create a copy to avoid modifying the original
          const assetCopy = {...asset};
          
          // Make sure user_balance is always available (default to 0)
          if (typeof assetCopy.user_balance === 'undefined') {
            assetCopy.user_balance = 0;
          }
          
          return assetCopy;
        });
    },
    
    // Combined transactions (invoices + payments)
    combinedTransactions() {
      // Check if state is defined
      if (!this.state || !this.state.invoices || !this.state.payments) {
        return [];
      }
      
      // Ensure we have arrays to work with
      const safeInvoices = Array.isArray(this.state.invoices) ? this.state.invoices : [];
      const safePayments = Array.isArray(this.state.payments) ? this.state.payments : [];
      
      // Combine and sort by date (most recent first)
      return [...safeInvoices, ...safePayments].sort((a, b) => {
        return new Date(b.created_at) - new Date(a.created_at);
      });
    },
    
    // Filtered transactions based on applied filters
    filteredTransactions() {
      // Check if combinedTransactions is available
      const combined = this.combinedTransactions();
      if (!combined || combined.length === 0) {
        return [];
      }
      
      // Check if state is defined
      if (!this.state || !this.state.filters) {
        return combined;
      }
      
      let result = [...combined];
      
      // Apply direction filter
      if (this.state.filters.direction && this.state.filters.direction !== 'all') {
        result = result.filter(tx => tx.direction === this.state.filters.direction);
      }
      
      // Apply status filter
      if (this.state.filters.status && this.state.filters.status !== 'all') {
        result = result.filter(tx => tx.status === this.state.filters.status);
      }
      
      // Apply search text filter
      if (this.state.filters.searchText) {
        const searchLower = this.state.filters.searchText.toLowerCase();
        result = result.filter(tx => 
          (tx.memo && tx.memo.toLowerCase().includes(searchLower)) ||
          (tx.payment_hash && tx.payment_hash.toLowerCase().includes(searchLower))
        );
      }
      
      // Apply date range filter
      if (this.state.filters.dateFrom || this.state.filters.dateTo) {
        result = result.filter(tx => {
          const txDate = new Date(tx.created_at);
          let matches = true;
          
          if (this.state.filters.dateFrom) {
            const fromDate = new Date(this.state.filters.dateFrom);
            fromDate.setHours(0, 0, 0, 0);
            if (txDate < fromDate) matches = false;
          }
          
          if (matches && this.state.filters.dateTo) {
            const toDate = new Date(this.state.filters.dateTo);
            toDate.setHours(23, 59, 59, 999);
            if (txDate > toDate) matches = false;
          }
          
          return matches;
        });
      }
      
      return result;
    },
    
    // Get current wallet
    getCurrentWallet() {
      return this.state ? this.state.currentWallet : null;
    },
    
    // Get asset by id
    getAssetById(assetId) {
      if (!assetId || !this.state || !this.state.assets || this.state.assets.length === 0) {
        return null;
      }
      
      return this.state.assets.find(asset => asset.asset_id === assetId) || null;
    },
    
    // Get asset name by id
    getAssetName(assetId) {
      const asset = this.getAssetById(assetId);
      return asset ? asset.name : 'Unknown';
    }
  },
  
  // Actions/mutations
  actions: {
    // Assets
    setAssets(assets) {
      if (this.state) {
        this.state.assets = assets || [];
      }
    },
    
    updateAsset(assetId, changes) {
      if (!this.state || !this.state.assets) return;
      
      const index = this.state.assets.findIndex(a => a.asset_id === assetId);
      if (index !== -1) {
        this.state.assets[index] = { ...this.state.assets[index], ...changes };
      }
    },
    
    setAssetsLoading(loading) {
      if (this.state) {
        this.state.assetsLoading = loading;
      }
    },
    
    // Invoices
    setInvoices(invoices) {
      if (this.state) {
        this.state.invoices = invoices || [];
      }
    },
    
    addInvoice(invoice) {
      if (!this.state || !this.state.invoices) return;
      
      // Check if invoice already exists
      const index = this.state.invoices.findIndex(i => i.id === invoice.id);
      if (index !== -1) {
        // Mark status change
        if (this.state.invoices[index].status !== invoice.status) {
          invoice._previousStatus = this.state.invoices[index].status;
          invoice._statusChanged = true;
        }
        
        // Update existing invoice
        this.state.invoices[index] = invoice;
      } else {
        // Mark as new
        invoice._isNew = true;
        
        // Add new invoice
        this.state.invoices.unshift(invoice);
      }
    },
    
    updateInvoice(invoiceId, changes) {
      if (!this.state || !this.state.invoices) return;
      
      const index = this.state.invoices.findIndex(i => i.id === invoiceId);
      if (index !== -1) {
        // Mark status change if status is changing
        if (changes.status && this.state.invoices[index].status !== changes.status) {
          changes._previousStatus = this.state.invoices[index].status;
          changes._statusChanged = true;
        }
        
        // Update invoice
        this.state.invoices[index] = { ...this.state.invoices[index], ...changes };
      }
    },
    
    // Payments
    setPayments(payments) {
      if (this.state) {
        this.state.payments = payments || [];
      }
    },
    
    addPayment(payment) {
      if (!this.state || !this.state.payments) return;
      
      // Check if payment already exists
      const index = this.state.payments.findIndex(p => p.id === payment.id);
      if (index !== -1) {
        // Mark status change
        if (this.state.payments[index].status !== payment.status) {
          payment._previousStatus = this.state.payments[index].status;
          payment._statusChanged = true;
        }
        
        // Update existing payment
        this.state.payments[index] = payment;
      } else {
        // Mark as new
        payment._isNew = true;
        
        // Add new payment
        this.state.payments.unshift(payment);
      }
    },
    
    updatePayment(paymentId, changes) {
      if (!this.state || !this.state.payments) return;
      
      const index = this.state.payments.findIndex(p => p.id === paymentId);
      if (index !== -1) {
        // Mark status change if status is changing
        if (changes.status && this.state.payments[index].status !== changes.status) {
          changes._previousStatus = this.state.payments[index].status;
          changes._statusChanged = true;
        }
        
        // Update payment
        this.state.payments[index] = { ...this.state.payments[index], ...changes };
      }
    },
    
    setTransactionsLoading(loading) {
      if (this.state) {
        this.state.transactionsLoading = loading;
      }
    },
    
    // Current wallet
    setCurrentWallet(wallet) {
      if (this.state) {
        this.state.currentWallet = wallet;
      }
    },
    
    // Filters
    setFilter(key, value) {
      if (this.state && this.state.filters && key in this.state.filters) {
        this.state.filters[key] = value;
      }
    },
    
    setDateFilter(from, to) {
      if (this.state && this.state.filters) {
        this.state.filters.dateFrom = from;
        this.state.filters.dateTo = to;
      }
    },
    
    resetFilters() {
      if (this.state) {
        this.state.filters = {
          direction: 'all',
          status: 'all',
          searchText: '',
          dateFrom: null,
          dateTo: null
        };
      }
    },
    
    // WebSocket status
    setWebsocketStatus(status) {
      if (this.state) {
        this.state.websocketStatus = { ...this.state.websocketStatus, ...status };
      }
    },
    
    // WebSocket status methods only
  }
};

// Export the store instance
window.taprootStore = taprootStore;

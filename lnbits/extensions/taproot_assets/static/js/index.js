/**
 * Main JavaScript for Taproot Assets extension
 */

// Create the Vue application
window.app = Vue.createApp({
  mixins: [windowMixin],
  
  data() {
    return {
      // Settings
      settings: {
        tapd_host: '',
        tapd_network: 'signet',
        tapd_tls_cert_path: '',
        tapd_macaroon_path: '',
        tapd_macaroon_hex: '',
        lnd_macaroon_path: '',
        lnd_macaroon_hex: '',
        default_sat_fee: 1
      },
      showSettings: false,
      
      // Assets
      assets: [],
      
      // Invoices and payments
      invoices: [],
      payments: [],
      combinedTransactions: [],
      filteredTransactions: [],
      searchDate: {from: null, to: null},
      searchData: {
        wallet_id: null,
        payment_hash: null,
        status: null,
        memo: null,
        tag: null
      },
      filter: {
        direction: 'all',
        status: 'all'
      },

      // Form dialog for creating invoices - EXPLICITLY INITIALIZED
      invoiceDialog: {
        show: false,
        selectedAsset: null,
        form: {
          amount: 1,
          memo: '',
          expiry: 3600
        }
      },

      // Created invoice data
      createdInvoice: null,

      // For sending payments - EXPLICITLY INITIALIZED
      paymentDialog: {
        show: false,
        selectedAsset: null,
        form: {
          paymentRequest: '',
          amount: 0,
          feeLimit: 1000
        },
        inProgress: false
      },

      // Success dialog - EXPLICITLY INITIALIZED
      successDialog: {
        show: false
      },

      // Form submission tracking
      isSubmitting: false,

      // For transaction list display
      transactionsLoading: false,
      transitionEnabled: false,
      transactionsTable: {
        pagination: {
          rowsPerPage: 10,
          page: 1,
          sortBy: 'created_at',
          descending: true
        }
      },

      // WebSocket connection
      websockets: {
        invoices: null,
        payments: null,
        balances: null
      },
      websocketConnected: false,
      websocketReconnectTimeout: null,
      
      // Refresh state tracking
      refreshInterval: null,
      refreshCount: 0,
      isRefreshing: false
    }
  },
  computed: {
    // Filter to only show assets with channels and add user balance information
    filteredAssets() {
      if (!this.assets || this.assets.length === 0) return [];
      return this.assets
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
    maxInvoiceAmount() {
      if (!this.invoiceDialog.selectedAsset) return 0;

      const asset = this.invoiceDialog.selectedAsset;
      if (asset.channel_info) {
        const totalCapacity = parseFloat(asset.channel_info.capacity);
        const localBalance = parseFloat(asset.channel_info.local_balance);
        return totalCapacity - localBalance;
      }
      return parseFloat(asset.amount);
    },
    isInvoiceAmountValid() {
      if (!this.invoiceDialog.selectedAsset) return false;
      return parseFloat(this.invoiceDialog.form.amount) <= this.maxInvoiceAmount;
    },
    // Pagination label (X-Y of Z format like LNbits)
    paginationLabel() {
      const { page, rowsPerPage } = this.transactionsTable.pagination;
      const totalItems = this.filteredTransactions.length;
      
      // Always show actual count when there are items
      if (totalItems > 0) {
        const startIndex = Math.min((page - 1) * rowsPerPage + 1, totalItems);
        const endIndex = Math.min(startIndex + rowsPerPage - 1, totalItems);
        return `${startIndex}-${endIndex} of ${totalItems}`;
      }
      
      return '0-0 of 0';
    }
  },
  methods: {
    // Helper method to find asset name by asset_id
    findAssetName(assetId) {
      if (!assetId || !this.assets || this.assets.length === 0) return null;
      const asset = this.assets.find(a => a.asset_id === assetId);
      return asset ? asset.name : null;
    },

    // Get just the asset name without "Taproot Asset Transfer:" prefix
    getAssetNameFromId(assetId) {
      return this.findAssetName(assetId);
    },

    // Check if a channel is active (used for styling)
    isChannelActive(asset) {
      return asset.channel_info && asset.channel_info.active !== false;
    },
    
    // Check if user can send this asset (has balance)
    canSendAsset(asset) {
      // First check if asset is active
      if (asset.channel_info && asset.channel_info.active === false) {
        return false;
      }
      
      // Then check if user has balance
      const userBalance = asset.user_balance || 0;
      return userBalance > 0;
    },

    // Format transaction date consistently
    formatTransactionDate,
    // Shortify long text (like payment hash)
    shortify,
    // Copy text to clipboard
    copyText(text) {
      copyText(text, notification => {
        this.$q.notify(notification);
      });
    },
    // Get status color
    getStatusColor,
    
    // Settings methods
    toggleSettings() {
      this.showSettings = !this.showSettings
    },
    
    getSettings() {
      if (!this.g.user.wallets.length) return;
      const wallet = this.g.user.wallets[0];

      getSettings(wallet.adminkey)
        .then(response => {
          this.settings = response.data;
        })
        .catch(err => {
          console.error('Failed to fetch settings:', err);
        });
    },
    
    saveSettings() {
      if (!this.g.user.wallets.length) return;
      const wallet = this.g.user.wallets[0];

      saveSettings(wallet.adminkey, this.settings)
        .then(response => {
          this.settings = response.data;
          this.showSettings = false;
        })
        .catch(err => {
          console.error('Failed to save settings:', err);
        });
    },
    
    getAssets() {
      if (!this.g.user.wallets.length || this.isRefreshing) return;
      
      this.isRefreshing = true;
      const wallet = this.g.user.wallets[0];

      console.log('Fetching assets...');
      
      getAssets(wallet.adminkey)
        .then(response => {
          console.log('Assets received:', response.data);
          
          // Create a new array instead of modifying the existing one
          const newAssets = Array.isArray(response.data) ? JSON.parse(JSON.stringify(response.data)) : [];
          
          // Log asset balances for debugging
          if (newAssets.length > 0) {
            const balances = newAssets
              .filter(asset => asset.channel_info)
              .map(asset => ({
                name: asset.name,
                channel_balance: asset.channel_info.local_balance,
                user_balance: asset.user_balance || 0
              }));
            console.log('Current asset balances:', balances);
          }
          
          // Replace the assets array
          this.assets = newAssets;
          
          if (this.assets.length > 0) {
            this.updateTransactionDescriptions();
          }
        })
        .catch(err => {
          console.error('Failed to fetch assets:', err);
          this.assets = [];
        })
        .finally(() => {
          this.isRefreshing = false;
        });
    },
    
    updateTransactionDescriptions() {
      // Update both invoices and payments with asset names
      const updateMemo = (item) => {
        const assetName = this.findAssetName(item.asset_id);
        if (assetName) {
          item.memo = `Taproot Asset Transfer: ${assetName}`;
        }
      };
      
      this.invoices.forEach(updateMemo);
      this.payments.forEach(updateMemo);
      
      // Refresh combined transactions
      this.combineTransactions();
    },
    
    getInvoices(isInitialLoad = false) {
      if (!this.g.user.wallets.length) return;
      const wallet = this.g.user.wallets[0];

      // Only show loading indicator on initial load
      if (isInitialLoad || this.invoices.length === 0) {
        this.transactionsLoading = true;
      }

      const timestamp = new Date().getTime();
      this.refreshCount++;

      getInvoices(wallet.adminkey)
        .then(response => {
          // Process invoices with asset names
          const processedInvoices = Array.isArray(response.data)
            ? response.data.map(invoice => {
                const mappedInvoice = mapInvoice(invoice);
                const assetName = this.findAssetName(mappedInvoice.asset_id);
                if (assetName) {
                  mappedInvoice.memo = `Taproot Asset Transfer: ${assetName}`;
                }
                return mappedInvoice;
              })
            : [];

          // Update or set invoices based on changes
          if (this.invoices.length === 0 || isInitialLoad) {
            this.invoices = processedInvoices;
          } else if (this.checkForChanges(processedInvoices, this.invoices)) {
            this.invoices = processedInvoices;
          }

          // Combine transactions and enable transitions
          this.combineTransactions();
          this.applyFilters();
          
          if (!this.transitionEnabled) {
            setTimeout(() => {
              this.transitionEnabled = true;
            }, 500);
          }
        })
        .catch(err => {
          console.error('Failed to fetch invoices:', err);
        })
        .finally(() => {
          this.transactionsLoading = false;
        });
    },
    
    getPayments(isInitialLoad = false) {
      if (!this.g.user.wallets.length) return;
      const wallet = this.g.user.wallets[0];

      // Only show loading indicator if needed
      if ((isInitialLoad || this.payments.length === 0) && !this.transactionsLoading) {
        this.transactionsLoading = true;
      }

      getPayments(wallet.adminkey)
        .then(response => {
          // Process payments with asset names
          const processedPayments = Array.isArray(response.data)
            ? response.data.map(payment => {
                const mappedPayment = mapPayment(payment);
                const assetName = this.findAssetName(mappedPayment.asset_id);
                if (assetName) {
                  mappedPayment.memo = `Taproot Asset Transfer: ${assetName}`;
                }
                return mappedPayment;
              })
            : [];

          this.payments = processedPayments;
          this.combineTransactions();
          this.applyFilters();
        })
        .catch(err => {
          console.error('Failed to fetch payments:', err);
        })
        .finally(() => {
          this.transactionsLoading = false;
        });
    },
    
    combineTransactions() {
      // Combine invoices and payments, sort by date
      this.combinedTransactions = [
        ...this.invoices,
        ...this.payments
      ].sort((a, b) => {
        return new Date(b.created_at) - new Date(a.created_at);
      });
      
      // Apply filters and search
      this.applyFilters();
    },
    
    applyFilters() {
      let result = [...this.combinedTransactions];
      
      // Apply direction filter
      if (this.filter.direction !== 'all') {
        result = result.filter(tx => tx.direction === this.filter.direction);
      }
      
      // Apply status filter
      if (this.filter.status !== 'all') {
        result = result.filter(tx => tx.status === this.filter.status);
      }
      
      // Apply memo search
      if (this.searchData.memo) {
        const searchLower = this.searchData.memo.toLowerCase();
        result = result.filter(tx => 
          tx.memo && tx.memo.toLowerCase().includes(searchLower)
        );
      }
      
      // Apply payment hash search
      if (this.searchData.payment_hash) {
        const searchLower = this.searchData.payment_hash.toLowerCase();
        result = result.filter(tx =>
          tx.payment_hash && tx.payment_hash.toLowerCase().includes(searchLower)
        );
      }
      
      // Apply date range filter
      if (this.searchDate.from || this.searchDate.to) {
        result = result.filter(tx => {
          const txDate = new Date(tx.created_at);
          let matches = true;
          
          if (this.searchDate.from) {
            const fromDate = new Date(this.searchDate.from);
            fromDate.setHours(0, 0, 0, 0);
            if (txDate < fromDate) matches = false;
          }
          
          if (matches && this.searchDate.to) {
            const toDate = new Date(this.searchDate.to);
            toDate.setHours(23, 59, 59, 999);
            if (txDate > toDate) matches = false;
          }
          
          return matches;
        });
      }
      
      // Update filtered transactions
      this.filteredTransactions = result;
      
      // Reset to first page when filtering
      if (this.transactionsTable.pagination.page > 1) {
        this.transactionsTable.pagination.page = 1;
      }
      
      // Force correct pagination display if needed
      if (this.filteredTransactions.length > 0 && 
          (this.transactionsTable.pagination.page - 1) * this.transactionsTable.pagination.rowsPerPage >= this.filteredTransactions.length) {
        this.transactionsTable.pagination.page = 1;
      }
    },
    
    searchByDate() {
      this.applyFilters();
    },
    
    clearDateSearch() {
      this.searchDate = { from: null, to: null };
      this.applyFilters();
    },
    
    resetFilters() {
      this.filter = {
        direction: 'all',
        status: 'all'
      };
      this.searchData = {
        wallet_id: null,
        payment_hash: null,
        status: null,
        memo: null,
        tag: null
      };
      this.searchDate = { from: null, to: null };
      this.applyFilters();
    },

    // Check if transactions have changed
    checkForChanges(newItems, existingItems) {
      // Quick length check
      if (newItems.length !== existingItems.length) {
        return true;
      }

      // Create lookup map
      const existingMap = {};
      existingItems.forEach(item => {
        existingMap[item.id] = item;
      });

      let hasChanges = false;

      // Compare items
      for (const newItem of newItems) {
        const existingItem = existingMap[newItem.id];
        
        // New item
        if (!existingItem) {
          newItem._isNew = true;
          hasChanges = true;
          continue;
        }
        
        // Status changed
        if (existingItem.status !== newItem.status) {
          newItem._previousStatus = existingItem.status;
          newItem._statusChanged = true;
          hasChanges = true;
        }
      }

      return hasChanges;
    },
    
    // Setup WebSocket connections
    setupWebSockets() {
      if (!this.g.user.wallets.length) return;
      
      const wallet = this.g.user.wallets[0];
      const userId = this.g.user.id;
      
      // Close any existing connections
      this.closeWebSockets();
      
      // Create WebSocket connections
      try {
        // Connect to invoice updates
        const invoicesWsUrl = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/api/v1/ws/taproot-assets-invoices-${userId}`;
        this.websockets.invoices = new WebSocket(invoicesWsUrl);
        this.websockets.invoices.onmessage = this.handleInvoiceWebSocketMessage;
        this.websockets.invoices.onclose = () => this.handleWebSocketClose('invoices');
        this.websockets.invoices.onerror = (err) => console.error('Invoice WebSocket error:', err);
        
        // Connect to payment updates
        const paymentsWsUrl = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/api/v1/ws/taproot-assets-payments-${userId}`;
        this.websockets.payments = new WebSocket(paymentsWsUrl);
        this.websockets.payments.onmessage = this.handlePaymentWebSocketMessage;
        this.websockets.payments.onclose = () => this.handleWebSocketClose('payments');
        this.websockets.payments.onerror = (err) => console.error('Payment WebSocket error:', err);
        
        // Connect to balances updates
        const balancesWsUrl = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/api/v1/ws/taproot-assets-balances-${userId}`;
        this.websockets.balances = new WebSocket(balancesWsUrl);
        this.websockets.balances.onmessage = this.handleBalancesWebSocketMessage;
        this.websockets.balances.onclose = () => this.handleWebSocketClose('balances');
        this.websockets.balances.onerror = (err) => console.error('Balances WebSocket error:', err);
        
        this.websocketConnected = true;
        console.log('WebSocket connections established');
      } catch (e) {
        console.error('Failed to setup WebSockets:', e);
        this.websocketConnected = false;
        // Fallback to polling
        this.startAutoRefresh();
      }
    },
    
    handleInvoiceWebSocketMessage(event) {
      try {
        const data = JSON.parse(event.data);
        console.log('Invoice WebSocket message:', data);
        
        if (data.type === 'invoice_update' && data.data) {
          // Find existing invoice
          const index = this.invoices.findIndex(invoice => invoice.id === data.data.id);
          
          if (index !== -1) {
            // Update existing invoice - using Vue 3 reactive approach
            const updatedInvoice = mapInvoice({
              ...this.invoices[index],
              ...data.data
            });
            
            // Mark as updated for animation
            updatedInvoice._statusChanged = true;
            
            // Update in array (Vue 3 way)
            this.invoices[index] = updatedInvoice;
            
            // Notify user about paid invoices and force asset refresh
            if (data.data.status === 'paid' && this.invoices[index].status !== 'paid') {
              const assetName = this.findAssetName(data.data.asset_id) || 'Unknown Asset';
              const amount = data.data.asset_amount || this.invoices[index].asset_amount;
              this.$q.notify({
                message: `Invoice Paid: ${amount} ${assetName}`,
                color: 'positive',
                icon: 'check_circle',
                timeout: 2000
              });
              
              // Force a direct refresh of assets after payment
              console.log('Invoice paid - scheduling asset refresh');
              setTimeout(() => {
                console.log('Running delayed asset refresh');
                this.getAssets();
              }, 500);
            }
          } else {
            // Add new invoice
            const newInvoice = mapInvoice(data.data);
            newInvoice._isNew = true;
            this.invoices.push(newInvoice);
          }
          
          // Update combined transactions
          this.combineTransactions();
        }
      } catch (e) {
        console.error('Error handling invoice WebSocket message:', e);
      }
    },
    
    handlePaymentWebSocketMessage(event) {
      try {
        const data = JSON.parse(event.data);
        console.log('Payment WebSocket message:', data);
        
        if (data.type === 'payment_update' && data.data) {
          // Find existing payment
          const index = this.payments.findIndex(payment => payment.id === data.data.id);
          
          if (index !== -1) {
            // Update existing payment - using Vue 3 reactive approach
            const updatedPayment = mapPayment({
              ...this.payments[index],
              ...data.data
            });
            
            // Mark as updated for animation
            updatedPayment._statusChanged = true;
            
            // Update in array (Vue 3 way)
            this.payments[index] = updatedPayment;
          } else {
            // Add new payment
            const newPayment = mapPayment(data.data);
            newPayment._isNew = true;
            this.payments.push(newPayment);
          }
          
          // Update combined transactions
          this.combineTransactions();
        }
      } catch (e) {
        console.error('Error handling payment WebSocket message:', e);
      }
    },
    
    handleBalancesWebSocketMessage(event) {
      try {
        const data = JSON.parse(event.data);
        console.log('Balances WebSocket message:', data);
        
        if (data.type === 'assets_update' && Array.isArray(data.data)) {
          console.log('New assets data from WebSocket:', data.data);
          
          // Create a completely new array with deep copies of each asset
          const newAssets = JSON.parse(JSON.stringify(data.data));
          
          // Log the current assets for comparison
          console.log('Current assets before update:', this.assets);
          
          // Replace the assets array with the new data
          this.assets = newAssets;
          
          // Log the updated assets
          console.log('Assets after update:', this.assets);
          
          // Update transaction descriptions with new asset names
          this.updateTransactionDescriptions();
        }
      } catch (e) {
        console.error('Error handling balances WebSocket message:', e);
      }
    },
    
    handleWebSocketClose(type) {
      console.log(`WebSocket ${type} connection closed`);
      this.websockets[type] = null;
      
      // Check if all connections are closed
      if (Object.values(this.websockets).every(ws => ws === null)) {
        this.websocketConnected = false;
        
        // Try to reconnect after delay
        if (!this.websocketReconnectTimeout) {
          this.websocketReconnectTimeout = setTimeout(() => {
            this.setupWebSockets();
            this.websocketReconnectTimeout = null;
          }, 5000);
        }
        
        // Fallback to polling while disconnected
        this.startAutoRefresh();
      }
    },
    
    closeWebSockets() {
      // Close all WebSocket connections
      Object.keys(this.websockets).forEach(key => {
        if (this.websockets[key]) {
          try {
            this.websockets[key].close();
          } catch (e) {
            console.error(`Error closing ${key} WebSocket:`, e);
          }
          this.websockets[key] = null;
        }
      });
      
      // Clear reconnect timeout if exists
      if (this.websocketReconnectTimeout) {
        clearTimeout(this.websocketReconnectTimeout);
        this.websocketReconnectTimeout = null;
      }
      
      this.websocketConnected = false;
    },
    
    // CSV export functions
    exportTransactionsCSV() {
      const rows = this.filteredTransactions.map(tx => {
        // Format data for CSV
        return {
          date: this.formatTransactionDate(tx.created_at),
          type: tx.direction === 'incoming' ? 'RECEIVED' : 'SENT',
          description: tx.memo || '',
          amount: tx.asset_amount || tx.extra?.asset_amount || '',
          asset: this.findAssetName(tx.asset_id) || tx.asset_id || '',
          status: tx.status || ''
        };
      });
      
      // Generate CSV
      downloadCSV(rows, 'taproot-asset-transactions.csv', this.$q.notify);
    },
    
    exportTransactionsCSVWithDetails() {
      const rows = this.filteredTransactions.map(tx => {
        // Format data for detailed CSV
        const baseData = {
          date: this.formatTransactionDate(tx.created_at),
          type: tx.direction === 'incoming' ? 'RECEIVED' : 'SENT',
          description: tx.memo || '',
          amount: tx.asset_amount || tx.extra?.asset_amount || '',
          asset: this.findAssetName(tx.asset_id) || tx.asset_id || '',
          status: tx.status || '',
          id: tx.id || '',
          payment_hash: tx.payment_hash || ''
        };
        
        // Add payment-specific fields
        if (tx.direction === 'outgoing') {
          baseData.fee_sats = tx.fee_sats || tx.extra?.fee_sats || '';
          baseData.preimage = tx.preimage || '';
        }
        
        // Add invoice-specific fields
        if (tx.direction === 'incoming') {
          baseData.satoshi_amount = tx.satoshi_amount || '';
          baseData.expires_at = tx.expires_at ? this.formatTransactionDate(tx.expires_at) : '';
          baseData.paid_at = tx.paid_at ? this.formatTransactionDate(tx.paid_at) : '';
        }
        
        return baseData;
      });
      
      // Generate CSV with more details
      downloadCSV(rows, 'taproot-asset-transactions-details.csv', this.$q.notify);
    },
    
    // Invoice dialog methods
    openInvoiceDialog(asset) {
      // Refresh assets first to ensure we have the latest channel status
      this.getAssets();
      
      // Don't allow creating invoices for inactive channels
      if (asset.channel_info && asset.channel_info.active === false) {
        this.$q.notify({
          message: 'Cannot create invoice for inactive channel',
          color: 'negative',
          icon: 'warning',
          timeout: 2000
        });
        return;
      }
      
      this.resetInvoiceForm();
      this.invoiceDialog.selectedAsset = asset;
      this.invoiceDialog.show = true;
    },
    
    resetInvoiceForm() {
      this.invoiceDialog.form = {
        amount: 1,
        memo: '',
        expiry: 3600
      };
      this.isSubmitting = false;
      this.createdInvoice = null;
    },
    
    closeInvoiceDialog() {
      this.invoiceDialog.show = false;
      this.resetInvoiceForm();
    },
    
    submitInvoiceForm() {
      if (this.isSubmitting || !this.g.user.wallets.length) return;
      
      const wallet = this.g.user.wallets[0];
      this.isSubmitting = true;

      // Build request payload
      const payload = {
        asset_id: this.invoiceDialog.selectedAsset.asset_id || '',
        amount: parseFloat(this.invoiceDialog.form.amount),
        memo: this.invoiceDialog.form.memo,
        expiry: this.invoiceDialog.form.expiry
      };

      // Add peer_pubkey if available
      if (this.invoiceDialog.selectedAsset.channel_info?.peer_pubkey) {
        payload.peer_pubkey = this.invoiceDialog.selectedAsset.channel_info.peer_pubkey;
      }

      createInvoice(wallet.adminkey, payload)
        .then(response => {
          this.createdInvoice = response.data;

          // Add asset name for display
          if (this.invoiceDialog.selectedAsset?.name) {
            this.createdInvoice.asset_name = this.invoiceDialog.selectedAsset.name;
          }

          // Copy to clipboard
          this.copyInvoice(response.data.payment_request || response.data.id);

          // WebSockets will handle UI updates, but refresh just in case
          this.refreshTransactions();
        })
        .catch(err => {
          console.error('Failed to create invoice:', err);
          
          // Check for specific error patterns
          let errorMessage = 'Failed to create invoice';
          
          if (err.response && err.response.data && err.response.data.detail) {
            const errorDetail = err.response.data.detail.toLowerCase();
            
            // Check for offline channel or no channel found errors
            if (errorDetail.includes('no asset channel found') || 
                errorDetail.includes('no channel balance') ||
                errorDetail.includes('channel not found') ||
                errorDetail.includes('peer channel') ||
                errorDetail.includes('offline') ||
                errorDetail.includes('unavailable')) {
              
              errorMessage = 'Channel appears to be offline or unavailable. Refreshing assets...';
              
              // Automatically refresh assets to get updated channel status
              this.getAssets();
              
              // Close the dialog
              this.closeInvoiceDialog();
            } else {
              // Use the server-provided error message
              errorMessage = err.response.data.detail;
            }
          }
          
          // Show error notification
          this.$q.notify({
            message: errorMessage,
            color: 'negative',
            icon: 'warning',
            timeout: 2000
          });
        })
        .finally(() => {
          this.isSubmitting = false;
        });
    },
    
    // Payment dialog methods
    openPaymentDialog(asset) {
      // Refresh assets first to ensure we have the latest channel status and balance
      this.getAssets();
      
      // Don't allow payments from inactive channels
      if (asset.channel_info && asset.channel_info.active === false) {
        this.$q.notify({
          message: 'Cannot send payment from inactive channel',
          color: 'negative',
          icon: 'warning',
          timeout: 2000
        });
        return;
      }
      
      // Check if user has balance
      if (!asset.user_balance || asset.user_balance <= 0) {
        this.$q.notify({
          message: 'You have zero balance for this asset',
          color: 'negative',
          icon: 'warning',
          timeout: 2000
        });
        return;
      }
      
      this.resetPaymentForm();
      this.paymentDialog.selectedAsset = asset;
      this.paymentDialog.show = true;
    },
    
    resetPaymentForm() {
      this.paymentDialog.form = {
        paymentRequest: '',
        amount: 0,
        feeLimit: 1000
      };
      this.paymentDialog.inProgress = false;
    },
    
    closePaymentDialog() {
      this.paymentDialog.show = false;
      this.resetPaymentForm();
    },
    
    // Extract amount from BOLT11 invoice
    extractAmountFromInvoice(paymentRequest) {
      if (!paymentRequest) return 0;
      
      try {
        // Try to decode using bolt11 library
        const decoded = bolt11.decode(paymentRequest);
        
        if (decoded && decoded.satoshis) {
          return decoded.satoshis / 1000; // Convert to asset units
        } else if (decoded && decoded.millisatoshis) {
          return decoded.millisatoshis / 1000000; // Convert msat to asset units
        }
      } catch (e) {
        console.error('Failed to decode invoice:', e);
      }
      
      return 0;
    },
    
    // Add a watcher for payment request to update amount
    watchPaymentRequest(val) {
      if (val) {
        const amount = this.extractAmountFromInvoice(val);
        this.paymentDialog.form.amount = amount;
      } else {
        this.paymentDialog.form.amount = 0;
      }
    },
    
    async submitPaymentForm() {
      if (this.paymentDialog.inProgress || !this.g.user.wallets.length) return;
      if (!this.paymentDialog.form.paymentRequest) {
        this.$q.notify({
          message: 'Please enter an invoice to pay',
          color: 'negative',
          icon: 'warning',
          timeout: 2000
        });
        return;
      }
      
      // Check if payment amount exceeds user's balance
      const userBalance = this.paymentDialog.selectedAsset?.user_balance || 0;
      if (this.paymentDialog.form.amount > userBalance) {
        this.$q.notify({
          message: `Payment amount (${this.paymentDialog.form.amount}) exceeds your available balance (${userBalance})`,
          color: 'negative',
          icon: 'warning',
          timeout: 3000
        });
        return;
      }

      try {
        this.paymentDialog.inProgress = true;
        const wallet = this.g.user.wallets[0];

        // Create payload
        const payload = {
          payment_request: this.paymentDialog.form.paymentRequest,
          fee_limit_sats: this.paymentDialog.form.feeLimit
        };

        // Add peer_pubkey if available
        if (this.paymentDialog.selectedAsset?.channel_info?.peer_pubkey) {
          payload.peer_pubkey = this.paymentDialog.selectedAsset.channel_info.peer_pubkey;
        }

        // Make the payment request
        const response = await payInvoice(wallet.adminkey, payload);

        // Show success and refresh data
        this.paymentDialog.show = false;
        this.successDialog.show = true;
        
        // WebSockets will handle UI updates, but refresh just in case
        await this.refreshTransactions();
        
        // Force asset refresh after sending payment
        setTimeout(() => {
          console.log('Payment completed - refreshing assets directly');
          this.getAssets();
        }, 500);

      } catch (error) {
        console.error('Payment failed:', error);
        
        // Check for specific error patterns
        let errorMessage = 'Payment failed';
        
        if (error.response && error.response.data && error.response.data.detail) {
          const errorDetail = error.response.data.detail.toLowerCase();
          
          // Check for offline channel or channel-related errors
          if (errorDetail.includes('no asset channel') || 
              errorDetail.includes('insufficient channel balance') ||
              errorDetail.includes('channel not found') ||
              errorDetail.includes('peer') ||
              errorDetail.includes('offline') ||
              errorDetail.includes('unavailable')) {
            
            errorMessage = 'Channel appears to be offline or unavailable. Refreshing assets...';
            
            // Automatically refresh assets to get updated channel status
            await this.getAssets();
            
            // Close the dialog
            this.paymentDialog.show = false;
          } else {
            // Use the server-provided error message
            errorMessage = error.response.data.detail;
          }
        }
        
        // Show error notification
        this.$q.notify({
          message: errorMessage,
          color: 'negative',
          icon: 'warning',
          timeout: 2000
        });
      } finally {
        this.paymentDialog.inProgress = false;
      }
    },
    
    // Invoice copy helper
    copyInvoice(invoice) {
      const textToCopy = typeof invoice === 'string'
        ? invoice
        : (invoice.payment_request || invoice.id || JSON.stringify(invoice) || 'No invoice data available');

      this.copyText(textToCopy);
    },
    
    // Refresh methods
    refreshTransactions() {
      this.getInvoices(true);
      this.getPayments(true);
    },
    
    startAutoRefresh() {
      // Only start polling if WebSockets are not connected
      if (this.websocketConnected) return;
      
      this.stopAutoRefresh();
      this.refreshInterval = setInterval(() => {
        this.getAssets();
        this.getInvoices();
        this.getPayments();
      }, 10000); // 10 seconds
    },
    
    stopAutoRefresh() {
      if (this.refreshInterval) {
        clearInterval(this.refreshInterval);
        this.refreshInterval = null;
      }
    }
  },
  
  created() {
    console.log("Vue app created");
    
    if (this.g.user.wallets.length) {
      this.getSettings();
      this.getAssets();
      this.getInvoices(true);
      this.getPayments(true);
      
      // Try to setup WebSockets first
      this.setupWebSockets();
    }
  },
  
  mounted() {
    console.log("Vue app mounted");
    setTimeout(() => {
      this.refreshTransactions();
    }, 500);
    
    // Add watcher for payment request to automatically update amount
    this.$watch('paymentDialog.form.paymentRequest', this.watchPaymentRequest);
  },
  
  activated() {
    console.log("Vue app activated");
    if (this.g.user.wallets.length) {
      this.resetInvoiceForm();
      this.resetPaymentForm();
      this.refreshTransactions();
      this.getAssets();
      
      // Try to reconnect WebSockets if disconnected
      if (!this.websocketConnected) {
        this.setupWebSockets();
      }
    }
  },
  
  deactivated() {
    this.stopAutoRefresh();
  },
  
  beforeUnmount() {
    this.stopAutoRefresh();
    this.closeWebSockets();
  }
});

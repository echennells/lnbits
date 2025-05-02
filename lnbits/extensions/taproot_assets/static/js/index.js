/**
 * Main JavaScript for Taproot Assets extension
 * Fixed version with original data handling approach
 */

// Create the Vue application
window.app = Vue.createApp({
  mixins: [windowMixin],
  
  data() {
    return {
      // Assets
      assets: [],
      assetsLoading: false,
      
      // Transactions
      invoices: [],
      payments: [],
      combinedTransactions: [],
      filteredTransactions: [],
      transactionsLoading: false,
      
      // For transaction list display
      transactionsTable: {
        pagination: {
          rowsPerPage: 10,
          page: 1,
          sortBy: 'created_at',
          descending: true
        }
      },
      
      // Search and filter
      searchDate: {from: null, to: null},
      filters: {
        direction: 'all',
        status: 'all',
        searchText: ''
      },
      
      // Form dialog for creating invoices
      invoiceDialog: {
        show: false,
        selectedAsset: null,
        form: {
          amount: 1,
          memo: '',
          expiry: 3600
        }
      },

      // Created invoice popup dialog with QR code
      createdInvoiceDialog: {
        show: false,
        title: 'Invoice Created'
      },

      // Created invoice data
      createdInvoice: null,

      // For sending payments
      paymentDialog: {
        show: false,
        selectedAsset: null,
        form: {
          paymentRequest: '',
          amount: 0,
          feeLimit: 1000
        },
        inProgress: false,
        invoiceDecodeError: false
      },

      // Success dialog
      successDialog: {
        show: false,
        message: 'Payment has been sent successfully.',
        title: 'Payment Successful!'
      },

      // Form submission tracking
      isSubmitting: false,

      // Refresh state tracking
      refreshInterval: null,
      isRefreshing: false,
      
      // Transition state for animations
      transitionEnabled: false,
      
      // User settings
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
      
      // WebSocket status
      websocketStatus: {
        connected: false,
        reconnecting: false,
        fallbackPolling: false
      }
    }
  },
  computed: {
    // Access the centralized store
    store() {
      // Check if the store is available globally
      return window.taprootStore || null;
    },
    
    // Filtered assets from local state
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
    
    // Maximum invoice amount
    maxInvoiceAmount() {
      if (!this.invoiceDialog.selectedAsset) return 0;
      return AssetService.getMaxReceivableAmount(this.invoiceDialog.selectedAsset);
    },
    
    // Check if invoice amount is valid
    isInvoiceAmountValid() {
      if (!this.invoiceDialog.selectedAsset) return false;
      return parseFloat(this.invoiceDialog.form.amount) <= this.maxInvoiceAmount;
    },
    
    // Pagination label (X-Y of Z format like LNbits)
    paginationLabel() {
      const { page, rowsPerPage } = this.transactionsTable.pagination;
      const totalItems = this.filteredTransactions ? this.filteredTransactions.length : 0;
      
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
    getAssetNameFromId(assetId) {
      return AssetService.getAssetName(assetId);
    },

    // Check if a channel is active (used for styling)
    isChannelActive(asset) {
      return asset && asset.channel_info && asset.channel_info.active !== false;
    },
    
    // Check if user can send this asset (has balance)
    canSendAsset(asset) {
      return AssetService.canSendAsset(asset);
    },
    
    // Get maximum receivable amount for an asset
    getMaxReceivableAmount(asset) {
      return AssetService.getMaxReceivableAmount(asset);
    },

    // Utility methods needed by templates
    formatTransactionDate(date) {
      return DataUtils.formatDate(date);
    },
    
    shortify(text, maxLength) {
      return DataUtils.shortify(text, maxLength);
    },
    
    copyText(text) {
      DataUtils.copyText(text, notification => {
        NotificationService.showSuccess(notification.message);
      });
    },
    
    getStatusColor(status) {
      return DataUtils.getStatusColor(status);
    },

    // Settings methods
    async getSettings() {
      try {
        if (!this.g.user.wallets || !this.g.user.wallets.length) return;
        const wallet = this.g.user.wallets[0];
        
        const response = await ApiService.getSettings(wallet.adminkey);
        
        // Update local settings
        this.settings = response.data;
        
        // Also update store if available
        if (this.store && this.store.actions) {
          this.store.actions.setSettings(response.data);
        }
      } catch (error) {
        NotificationService.processApiError(error, 'Failed to fetch settings');
      }
    },
    
    async saveSettings() {
      try {
        if (!this.g.user.wallets || !this.g.user.wallets.length) return;
        const wallet = this.g.user.wallets[0];
        
        const response = await ApiService.saveSettings(wallet.adminkey, this.settings);
        
        // Update local settings
        this.settings = response.data;
        
        // Also update store if available
        if (this.store && this.store.actions) {
          this.store.actions.setSettings(response.data);
        }
        
        NotificationService.showSuccess('Settings saved successfully');
      } catch (error) {
        NotificationService.processApiError(error, 'Failed to save settings');
      }
    },
    
    // Asset methods
    async getAssets() {
      if (!this.g.user.wallets || !this.g.user.wallets.length || this.isRefreshing) return;
      
      this.isRefreshing = true;
      this.assetsLoading = true;
      
      try {
        const wallet = this.g.user.wallets[0];
        // Get assets from service
        this.assets = await AssetService.getAssets(wallet);
      } catch (error) {
        console.error('Failed to fetch assets:', error);
        this.assets = [];
      } finally {
        this.assetsLoading = false;
        this.isRefreshing = false;
      }
    },
    
    // Transaction methods
    async getInvoices() {
      if (!this.g.user.wallets || !this.g.user.wallets.length) return;
      
      this.transactionsLoading = true;
      
      try {
        const wallet = this.g.user.wallets[0];
        
        // Use InvoiceService but store results locally
        const invoices = await InvoiceService.getInvoices(wallet, true);
        this.invoices = invoices;
        
        // Combine transactions after getting invoices
        this.combineTransactions();
        
        if (!this.transitionEnabled) {
          setTimeout(() => {
            this.transitionEnabled = true;
          }, 500);
        }
      } catch (error) {
        console.error('Failed to fetch invoices:', error);
        this.invoices = [];
      } finally {
        this.transactionsLoading = false;
      }
    },
    
    async getPayments() {
      if (!this.g.user.wallets || !this.g.user.wallets.length) return;
      
      this.transactionsLoading = true;
      
      try {
        const wallet = this.g.user.wallets[0];
        
        // Use PaymentService but store results locally
        const payments = await PaymentService.getPayments(wallet, true);
        this.payments = payments;
        
        // Combine transactions after getting payments
        this.combineTransactions();
      } catch (error) {
        console.error('Failed to fetch payments:', error);
        this.payments = [];
      } finally {
        this.transactionsLoading = false;
      }
    },
    
    combineTransactions() {
      // Ensure we have arrays to work with
      const safeInvoices = Array.isArray(this.invoices) ? this.invoices : [];
      const safePayments = Array.isArray(this.payments) ? this.payments : [];
      
      // Combine and sort by date (most recent first)
      this.combinedTransactions = [...safeInvoices, ...safePayments].sort((a, b) => {
        return new Date(b.created_at) - new Date(a.created_at);
      });
      
      // Apply filters to combined transactions
      this.applyFilters();
    },
    
    applyFilters() {
      let result = [...this.combinedTransactions];
      
      // Apply direction filter
      if (this.filters.direction && this.filters.direction !== 'all') {
        result = result.filter(tx => tx.direction === this.filters.direction);
      }
      
      // Apply status filter
      if (this.filters.status && this.filters.status !== 'all') {
        result = result.filter(tx => tx.status === this.filters.status);
      }
      
      // Apply search text filter
      if (this.filters.searchText) {
        const searchLower = this.filters.searchText.toLowerCase();
        result = result.filter(tx => 
          (tx.memo && tx.memo.toLowerCase().includes(searchLower)) ||
          (tx.payment_hash && tx.payment_hash.toLowerCase().includes(searchLower))
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
      
      // Set filtered transactions
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
      this.searchDate = { from: null, to: null };
      this.filters = {
        direction: 'all',
        status: 'all',
        searchText: ''
      };
      this.applyFilters();
    },

    // WebSocket handling
    initializeWebSockets() {
      if (!this.g.user || !this.g.user.id) return;
      
      WebSocketManager.initialize(this.g.user.id, {
        onPollingRequired: this.refreshData
      });
    },
    
    // CSV export functions
    exportTransactionsCSV() {
      const rows = this.filteredTransactions.map(tx => {
        return {
          date: DataUtils.formatDate(tx.created_at),
          type: tx.direction === 'incoming' ? 'RECEIVED' : 'SENT',
          description: tx.memo || '',
          amount: tx.asset_amount || tx.extra?.asset_amount || '',
          asset: this.getAssetNameFromId(tx.asset_id) || tx.asset_id || '',
          memo: tx.memo || '',
          status: tx.status || ''
        };
      });
      
      DataUtils.downloadCSV(rows, 'taproot-asset-transactions.csv', 
        notification => this.$q.notify(notification));
    },
    
    exportTransactionsCSVWithDetails() {
      const rows = this.filteredTransactions.map(tx => {
        const baseData = {
          date: DataUtils.formatDate(tx.created_at),
          type: tx.direction === 'incoming' ? 'RECEIVED' : 'SENT',
          description: tx.memo || '',
          amount: tx.asset_amount || tx.extra?.asset_amount || '',
          asset: this.getAssetNameFromId(tx.asset_id) || tx.asset_id || '',
          memo: tx.memo || '',
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
          baseData.expires_at = tx.expires_at ? DataUtils.formatDate(tx.expires_at) : '';
          baseData.paid_at = tx.paid_at ? DataUtils.formatDate(tx.paid_at) : '';
        }
        
        return baseData;
      });
      
      DataUtils.downloadCSV(rows, 'taproot-asset-transactions-details.csv', 
        notification => this.$q.notify(notification));
    },
    
    // Invoice dialog methods
    openInvoiceDialog(asset) {
      // Refresh assets first to ensure we have the latest channel status
      this.getAssets();
      
      // Don't allow creating invoices for inactive channels
      if (asset.channel_info && asset.channel_info.active === false) {
        NotificationService.showError('Cannot create invoice for inactive channel');
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
    
    async submitInvoiceForm() {
      if (this.isSubmitting || !this.g.user.wallets || !this.g.user.wallets.length) return;
      
      const wallet = this.g.user.wallets[0];
      this.isSubmitting = true;

      try {
        this.createdInvoice = await InvoiceService.createInvoice(
          wallet,
          this.invoiceDialog.selectedAsset,
          this.invoiceDialog.form
        );

        // Set a more descriptive title that includes the asset name
        this.createdInvoiceDialog.title = `${this.createdInvoice.asset_name || 'Asset'} Invoice`;

        // Close the invoice creation dialog and show the created invoice dialog
        this.invoiceDialog.show = false;
        this.createdInvoiceDialog.show = true;
        
        // Show notification
        NotificationService.notifyInvoiceCreated(this.createdInvoice);
        
        // Refresh transactions
        this.refreshTransactions();
      } catch (error) {
        // Special handling for channel offline errors
        const errorMessage = NotificationService.processApiError(error, 'Failed to create invoice');
        
        if (errorMessage.toLowerCase().includes('channel') && 
            (errorMessage.toLowerCase().includes('offline') || 
             errorMessage.toLowerCase().includes('unavailable'))) {
          // Automatically refresh assets to get updated channel status
          this.getAssets();
          
          // Close the dialog
          this.closeInvoiceDialog();
        }
      } finally {
        this.isSubmitting = false;
      }
    },
    
    // Payment dialog methods
    openPaymentDialog(asset) {
      // Refresh assets first to ensure we have the latest channel status and balance
      this.getAssets();
      
      // Don't allow payments from inactive channels
      if (asset.channel_info && asset.channel_info.active === false) {
        NotificationService.showError('Cannot send payment from inactive channel');
        return;
      }
      
      // Check if user has balance
      if (!asset.user_balance || asset.user_balance <= 0) {
        NotificationService.showError('You have zero balance for this asset');
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
      this.paymentDialog.invoiceDecodeError = false;
    },
    
    closePaymentDialog() {
      this.paymentDialog.show = false;
      this.resetPaymentForm();
    },
    
    async parseInvoice(paymentRequest) {
      if (!paymentRequest || paymentRequest.trim() === '') {
        this.paymentDialog.invoiceDecodeError = false;
        this.paymentDialog.form.amount = 0;
        return;
      }
      
      if (!this.g.user.wallets || !this.g.user.wallets.length) return;
      const wallet = this.g.user.wallets[0];
      
      try {
        // Use PaymentService to parse invoice
        const parsedInvoice = await PaymentService.parseInvoice(wallet, paymentRequest);
        
        // Update form with parsed data
        this.paymentDialog.form.amount = parsedInvoice.amount || 0;
        this.paymentDialog.invoiceDecodeError = false;
        
        // If amount is 0, warn the user
        if (parsedInvoice.amount === 0) {
          NotificationService.showWarning('Warning: Invoice has no specified amount');
        }
      } catch (error) {
        console.error('Failed to parse invoice:', error);
        this.paymentDialog.invoiceDecodeError = true;
        this.paymentDialog.form.amount = 0;
        NotificationService.showError('Invalid invoice format');
      }
    },
    
    async submitPaymentForm() {
      if (this.paymentDialog.inProgress || !this.g.user.wallets || !this.g.user.wallets.length) return;
      
      if (!this.paymentDialog.form.paymentRequest) {
        NotificationService.showError('Please enter an invoice to pay');
        return;
      }
      
      // Don't proceed if invoice is invalid
      if (this.paymentDialog.invoiceDecodeError) {
        NotificationService.showError('Cannot pay an invalid invoice');
        return;
      }

      try {
        this.paymentDialog.inProgress = true;
        const wallet = this.g.user.wallets[0];

        // Use PaymentService to pay invoice
        const paymentResult = await PaymentService.payInvoice(
          wallet,
          this.paymentDialog.selectedAsset,
          {
            paymentRequest: this.paymentDialog.form.paymentRequest,
            feeLimit: this.paymentDialog.form.feeLimit
          }
        );
        
        // Close payment dialog
        this.paymentDialog.show = false;
        
        // Get notification message and title
        const {title, message} = NotificationService.notifyPaymentSent(paymentResult);
        
        // Set success dialog content
        this.successDialog.title = title;
        this.successDialog.message = message;
        
        // Show success dialog
        this.successDialog.show = true;
        
        // Immediately refresh assets to get updated balances
        this.getAssets();
        
        // Also refresh transactions
        this.refreshTransactions();
      } catch (error) {
        // Check for special internal payment case
        if (error.isInternalPayment) {
          // Try to process as internal payment automatically
          try {
            NotificationService.showInfo(error.message);
            const success = await this.processInternalPayment(
              this.paymentDialog.form.paymentRequest, 
              this.paymentDialog.form.feeLimit
            );
            if (success) return; // Exit early as we're handling it
          } catch (internalPayError) {
            NotificationService.processApiError(
              internalPayError, 
              'Failed to process internal payment. Please try again.'
            );
          }
        } else {
          // Process standard error
          const errorMessage = NotificationService.processApiError(
            error,
            'Payment failed'
          );
          
          // Special handling for channel-related errors
          if (errorMessage.toLowerCase().includes('channel') && 
              (errorMessage.toLowerCase().includes('offline') || 
               errorMessage.toLowerCase().includes('unavailable'))) {
            // Automatically refresh assets to get updated channel status
            this.getAssets();
            
            // Close the dialog
            this.paymentDialog.show = false;
          }
        }
      } finally {
        this.paymentDialog.inProgress = false;
      }
    },
    
    // Process an internal payment
    async processInternalPayment(paymentRequest, feeLimit) {
      try {
        if (!this.g.user.wallets || !this.g.user.wallets.length) return false;
        
        this.paymentDialog.inProgress = true;
        const wallet = this.g.user.wallets[0];
        
        const paymentResult = await PaymentService.processInternalPayment(
          wallet,
          {
            paymentRequest: paymentRequest,
            feeLimit: feeLimit || 10
          }
        );
        
        // Close payment dialog
        this.paymentDialog.show = false;
        
        // Get notification message and title
        const {title, message} = NotificationService.notifyPaymentSent(paymentResult);
        
        // Set success dialog content
        this.successDialog.title = title || 'Internal Payment Processed';
        this.successDialog.message = message || 'Payment to another user on this node has been processed successfully.';
        this.successDialog.show = true;
        
        // Immediately refresh assets to show updated balances
        this.getAssets();
        
        // Also refresh transactions
        this.refreshTransactions();
        
        return true;
      } catch (error) {
        NotificationService.processApiError(error, 'Internal payment failed');
        return false;
      } finally {
        this.paymentDialog.inProgress = false;
      }
    },
    
    // Copy invoice to clipboard
    copyInvoice(invoice) {
      // Simply use the payment_request property directly
      const paymentRequest = invoice.payment_request;
      
      if (!paymentRequest) {
        console.error('Missing payment_request in invoice:', invoice);
        this.$q.notify({
          message: 'Error: No invoice data found',
          color: 'negative',
          icon: 'error',
          timeout: 2000
        });
        return;
      }
      
      if (window.Quasar && window.Quasar.copyToClipboard) {
        window.Quasar.copyToClipboard(paymentRequest)
          .then(() => {
            this.$q.notify({
              message: 'Invoice copied to clipboard!',
              color: 'positive',
              icon: 'check',
              timeout: 2000
            });
          })
          .catch(err => {
            console.error('Failed to copy to clipboard:', err);
            this.$q.notify({
              message: 'Failed to copy to clipboard',
              color: 'negative',
              icon: 'error',
              timeout: 2000
            });
          });
      } else {
        // Fallback to DataUtils
        DataUtils.copyText(paymentRequest, notification => {
          this.$q.notify(notification);
        });
      }
    },
    
    // Refresh methods
    refreshTransactions() {
      this.getInvoices();
      this.getPayments();
    },
    
    refreshData() {
      this.getAssets();
      this.getInvoices();
      this.getPayments();
    },
    
    startAutoRefresh() {
      // Only start if not already polling and WebSockets not connected
      if (this.refreshInterval || this.websocketStatus.connected) return;
      
      this.stopAutoRefresh();
      this.refreshInterval = setInterval(() => {
        this.refreshData();
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
    
    // Initialize only after app is created
    if (this.g.user && this.g.user.wallets && this.g.user.wallets.length) {
      this.getSettings();
      this.getAssets();
      this.getInvoices();
      this.getPayments();
      
      // Initialize WebSockets
      this.initializeWebSockets();
    }
  },
  
  mounted() {
    console.log("Vue app mounted");
    
    // Delayed refresh to make sure everything is ready
    setTimeout(() => {
      try {
        this.refreshTransactions();
      } catch (err) {
        console.error('Error refreshing transactions:', err);
      }
    }, 1000);
    
    // Add watcher for payment request to parse invoice on change
    this.$watch('paymentDialog.form.paymentRequest', (newValue) => {
      if (newValue) {
        this.parseInvoice(newValue);
      } else {
        this.paymentDialog.form.amount = 0;
        this.paymentDialog.invoiceDecodeError = false;
      }
    });
  },
  
  activated() {
    console.log("Vue app activated");
    if (this.g.user && this.g.user.wallets && this.g.user.wallets.length) {
      this.resetInvoiceForm();
      this.resetPaymentForm();
      this.refreshTransactions();
      this.getAssets();
      
      // Reconnect WebSockets if disconnected
      if (!this.websocketStatus.connected) {
        this.initializeWebSockets();
      }
      
      // Start polling if WebSockets are not connected
      if (!this.websocketStatus.connected) {
        this.startAutoRefresh();
      }
    }
  },
  
  deactivated() {
    this.stopAutoRefresh();
  },
  
  beforeUnmount() {
    this.stopAutoRefresh();
    
    // Clean up WebSocket manager
    if (window.WebSocketManager) {
      WebSocketManager.destroy();
    }
  }
});

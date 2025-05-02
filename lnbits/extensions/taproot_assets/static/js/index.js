/**
 * Main JavaScript for Taproot Assets extension
 * Refactored to use service-based architecture
 */

// Create the Vue application with i18n compatibility
window.app = Vue.createApp({
  mixins: [windowMixin],
  
  // Add a translation function to prevent $t errors
  methods: {
    $t(key) {
      // Simple fallback translation function
      return key;
    }
  },
  
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
      
      // Add localStorage availability flag
      hasLocalStorage: true,
      
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

      // WebSocket connection status
      websocketStatus: {
        connected: false,
        reconnecting: false,
        fallbackPolling: false
      },
      
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
      
      // Get maximum receivable amount using AssetService
      return AssetService.getMaxReceivableAmount(this.invoiceDialog.selectedAsset);
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
      return AssetService.getAssetName(assetId);
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
      return AssetService.canSendAsset(asset);
    },

    // Use shared DataUtils methods
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
    toggleSettings() {
      this.showSettings = !this.showSettings;
    },
    
    async getSettings() {
      try {
        if (!this.g.user.wallets.length) return;
        const wallet = this.g.user.wallets[0];
        
        const response = await ApiService.getSettings(wallet.adminkey);
        this.settings = response.data;
      } catch (error) {
        console.error('Failed to fetch settings:', error);
        NotificationService.processApiError(error, 'Failed to fetch settings');
      }
    },
    
    async saveSettings() {
      try {
        if (!this.g.user.wallets.length) return;
        const wallet = this.g.user.wallets[0];
        
        const response = await ApiService.saveSettings(wallet.adminkey, this.settings);
        this.settings = response.data;
        this.showSettings = false;
        NotificationService.showSuccess('Settings saved successfully');
      } catch (error) {
        console.error('Failed to save settings:', error);
        NotificationService.processApiError(error, 'Failed to save settings');
      }
    },
    
    async getAssets() {
      if (!this.g.user.wallets.length || this.isRefreshing) return;
      
      this.isRefreshing = true;
      const wallet = this.g.user.wallets[0];
      
      try {
        console.log('Fetching assets...');
        const assets = await AssetService.getAssets(wallet);
        
        // Replace the assets array
        this.assets = assets;
        
        if (this.assets.length > 0) {
          this.updateTransactionDescriptions();
        }
      } catch (error) {
        console.error('Failed to fetch assets:', error);
        this.assets = [];
      } finally {
        this.isRefreshing = false;
      }
    },
    
    updateTransactionDescriptions() {
      // Refresh combined transactions
      this.combineTransactions();
    },
    
    async getInvoices(isInitialLoad = false) {
      if (!this.g.user.wallets.length) return;
      const wallet = this.g.user.wallets[0];

      // Only show loading indicator on initial load
      if (isInitialLoad || this.invoices.length === 0) {
        this.transactionsLoading = true;
      }

      try {
        // Use InvoiceService to get invoices
        const invoices = await InvoiceService.getInvoices(wallet, true);
        
        // Check for changes in invoices
        const changes = InvoiceService.findChanges(invoices, this.invoices);
        
        // Apply changes if needed
        if (changes.new.length > 0 || changes.updated.length > 0) {
          // Update invoices array
          this.invoices = invoices;
          
          // Combine transactions
          this.combineTransactions();
        }
        
        // Enable transitions after initial load
        if (!this.transitionEnabled) {
          setTimeout(() => {
            this.transitionEnabled = true;
          }, 500);
        }
      } catch (error) {
        console.error('Failed to fetch invoices:', error);
      } finally {
        this.transactionsLoading = false;
      }
    },
    
    async getPayments(isInitialLoad = false) {
      if (!this.g.user.wallets.length) return;
      const wallet = this.g.user.wallets[0];

      // Only show loading indicator if needed
      if ((isInitialLoad || this.payments.length === 0) && !this.transactionsLoading) {
        this.transactionsLoading = true;
      }

      try {
        // Use PaymentService to get payments
        const payments = await PaymentService.getPayments(wallet, true);
        
        // Update payments array
        this.payments = payments;
        
        // Combine transactions
        this.combineTransactions();
      } catch (error) {
        console.error('Failed to fetch payments:', error);
      } finally {
        this.transactionsLoading = false;
      }
    },
    
    combineTransactions() {
      // Combine invoices and payments using DataUtils
      this.combinedTransactions = DataUtils.combineTransactions(this.invoices, this.payments);
      
      // Apply filters and search
      this.applyFilters();
    },
    
    applyFilters() {
      // Use DataUtils to filter transactions
      this.filteredTransactions = DataUtils.filterTransactions(
        this.combinedTransactions,
        this.filter,
        this.searchData,
        this.searchDate
      );
      
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

    // WebSocket handling methods
    initializeWebSockets() {
      if (!this.g.user || !this.g.user.id) return;
      
      // Initialize WebSocket manager with handlers
      WebSocketManager.initialize(this.g.user.id, {
        // Handler for invoice messages
        onInvoiceMessage: this.handleInvoiceWebSocketMessage,
        
        // Handler for payment messages
        onPaymentMessage: this.handlePaymentWebSocketMessage,
        
        // Handler for balance messages
        onBalanceMessage: this.handleBalancesWebSocketMessage,
        
        // Handler for connection state changes
        onConnectionChange: this.handleWebSocketConnectionChange,
        
        // Handler for fallback polling
        onPollingRequired: this.refreshData
      });
    },
    
    handleWebSocketConnectionChange(status) {
      // Update websocket status
      this.websocketStatus = status;
      
      // If we just connected, refresh data
      if (status.connected && !status.reconnecting) {
        this.refreshData();
      }
    },
    
    handleInvoiceWebSocketMessage(data) {
      try {
        if (data.type === 'invoice_update' && data.data) {
          // Debug the current state
          console.log('Current dialog state:', {
            dialogShowing: this.createdInvoiceDialog.show,
            hasCreatedInvoice: !!this.createdInvoice
          });
          
          if (this.createdInvoice) {
            console.log('Current displayed invoice:', {
              payment_hash: this.createdInvoice.payment_hash,
              id: this.createdInvoice.id,
              payment_request: this.createdInvoice.payment_request?.substring(0, 30) + '...'
            });
          }
          
          console.log('Received invoice update:', {
            id: data.data.id,
            payment_hash: data.data.payment_hash,
            status: data.data.status
          });
          
          // Check if this invoice was paid
          if (data.data.status === 'paid') {
            console.log('PAID INVOICE DETECTED');
            
            const assetName = this.findAssetName(data.data.asset_id) || 'Unknown Asset';
            const amount = data.data.asset_amount || 0;
            
            // Notify user about paid invoice
            NotificationService.notifyInvoicePaid({
              asset_name: assetName,
              asset_amount: amount,
              asset_id: data.data.asset_id
            });
            
            // Force an immediate refresh of assets
            console.log('Invoice paid - refreshing assets immediately');
            this.getAssets();
            
            // Check if we should close the invoice dialog
            if (this.createdInvoiceDialog.show && this.createdInvoice) {
              console.log('Checking if we should close the invoice dialog...');
              
              // Try multiple ways to match the invoice
              let matchFound = false;
              
              // Match by ID
              if (this.createdInvoice.id === data.data.id) {
                console.log('Match found by invoice ID');
                matchFound = true;
              }
              
              // Match by payment hash
              else if (this.createdInvoice.payment_hash === data.data.payment_hash) {
                console.log('Match found by payment hash');
                matchFound = true;
              }
              
              // If the displayed invoice is the one that was paid, close the dialog
              if (matchFound) {
                console.log('CLOSING INVOICE DIALOG - Match found between displayed invoice and paid invoice');
                // Close the dialog
                this.createdInvoiceDialog.show = false;
                
                // Show a notification
                NotificationService.showSuccess('Invoice has been paid');
              } else {
                console.log('Not closing dialog - displayed invoice does not match the paid one');
              }
            }
          }
          
          // Force refresh of invoices
          this.getInvoices();
        }
      } catch (e) {
        console.error('Error handling invoice WebSocket message:', e, e.stack);
      }
    },
    
    handlePaymentWebSocketMessage(data) {
      try {
        if (data.type === 'payment_update' && data.data) {
          console.log('Payment WebSocket message:', data);
          
          // Check if this is a completed payment
          if (data.data.status === 'completed') {
            console.log('Payment completed - refreshing assets immediately');
            this.getAssets();
          }
          
          // Force refresh of payments
          this.getPayments();
        }
      } catch (e) {
        console.error('Error handling payment WebSocket message:', e);
      }
    },
    
    handleBalancesWebSocketMessage(data) {
      try {
        if (data.type === 'assets_update' && Array.isArray(data.data)) {
          // Refresh from API when balance updates received
          if (!this.isRefreshing) {
            console.log('Balance WebSocket received - refreshing assets from API');
            this.getAssets();
          }
        }
      } catch (e) {
        console.error('Error handling balances WebSocket message:', e);
      }
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
          memo: tx.memo || '',
          status: tx.status || ''
        };
      });
      
      // Generate CSV using DataUtils
      DataUtils.downloadCSV(rows, 'taproot-asset-transactions.csv', 
        notification => this.$q.notify(notification));
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
          baseData.expires_at = tx.expires_at ? this.formatTransactionDate(tx.expires_at) : '';
          baseData.paid_at = tx.paid_at ? this.formatTransactionDate(tx.paid_at) : '';
        }
        
        return baseData;
      });
      
      // Generate CSV with more details
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
      if (this.isSubmitting || !this.g.user.wallets.length) return;
      
      const wallet = this.g.user.wallets[0];
      this.isSubmitting = true;

      try {
        // Use InvoiceService to create invoice
        const createdInvoice = await InvoiceService.createInvoice(
          wallet,
          this.invoiceDialog.selectedAsset,
          this.invoiceDialog.form
        );
        
        // Store the created invoice data
        this.createdInvoice = createdInvoice;

        // Set a more descriptive title that includes the asset name
        this.createdInvoiceDialog.title = `${this.createdInvoice.asset_name || 'Asset'} Invoice`;

        // Close the invoice creation dialog
        this.invoiceDialog.show = false;
        
        // Show the created invoice dialog with QR code
        this.createdInvoiceDialog.show = true;
        
        // Show notification
        NotificationService.notifyInvoiceCreated(createdInvoice);
        
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
    
    // Use service for invoice parsing
    async parseInvoice(paymentRequest) {
      if (!paymentRequest || paymentRequest.trim() === '') {
        this.paymentDialog.invoiceDecodeError = false;
        this.paymentDialog.form.amount = 0;
        return;
      }
      
      if (!this.g.user.wallets.length) return;
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
      if (this.paymentDialog.inProgress || !this.g.user.wallets.length) return;
      
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
        console.log('Payment completed - refreshing assets immediately');
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
            await this.getAssets();
            
            // Close the dialog
            this.paymentDialog.show = false;
          }
        }
      } finally {
        this.paymentDialog.inProgress = false;
      }
    },
    
    // Process an internal payment - between different users on the same node
    async processInternalPayment(paymentRequest, feeLimit) {
      try {
        if (!this.g.user.wallets.length) return false;
        
        this.paymentDialog.inProgress = true;
        const wallet = this.g.user.wallets[0];
        
        // Use PaymentService to process internal payment
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
        console.log('Internal payment completed - refreshing assets immediately');
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
    
    // Process a self-payment (backward compatibility)
    async processSelfPayment(paymentRequest, feeLimit) {
      try {
        if (!this.g.user.wallets.length) return false;
        
        this.paymentDialog.inProgress = true;
        const wallet = this.g.user.wallets[0];
        
        // Use PaymentService to process self-payment
        const paymentResult = await PaymentService.processSelfPayment(
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
        this.successDialog.title = title;
        this.successDialog.message = message;
        this.successDialog.show = true;
        
        // Immediately refresh assets to show updated balances 
        console.log('Self/Internal payment completed - refreshing assets immediately');
        this.getAssets();
        
        // Also refresh transactions
        this.refreshTransactions();
        
        return true;
      } catch (error) {
        NotificationService.processApiError(error, 'Self-payment failed');
        return false;
      } finally {
        this.paymentDialog.inProgress = false;
      }
    },
    
    // Copy invoice to clipboard
    copyInvoice(invoice) {
      // Make sure we're copying the payment_request property
      const paymentRequest = invoice.payment_request;
      
      if (!paymentRequest) {
        console.error('Missing payment_request in invoice:', invoice);
        NotificationService.showError('Error: No invoice data found');
        return;
      }
      
      console.log('Copying invoice payment request:', paymentRequest);
      
      try {
        // Use LNbits built-in copy if available
        if (window.LNbits && window.LNbits.utils && window.LNbits.utils.copy) {
          window.LNbits.utils.copy(paymentRequest);
          NotificationService.notifyCopied('Invoice');
        } else {
          // Direct clipboard API
          navigator.clipboard.writeText(paymentRequest)
            .then(() => {
              NotificationService.notifyCopied('Invoice');
            })
            .catch(err => {
              console.error('Failed to copy to clipboard:', err);
              NotificationService.showError('Failed to copy to clipboard');
            });
        }
      } catch (error) {
        console.error('Error copying invoice:', error);
        NotificationService.showError('Failed to copy invoice');
      }
    },
    
    // Refresh methods
    refreshTransactions() {
      this.getInvoices(true);
      this.getPayments(true);
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
    
    if (this.g.user && this.g.user.wallets && this.g.user.wallets.length) {
      this.getSettings();
      this.getAssets();
      this.getInvoices(true);
      this.getPayments(true);
      
      // Initialize WebSockets
      this.initializeWebSockets();
    }
  },
  
  mounted() {
    console.log("Vue app mounted");
    setTimeout(() => {
      this.refreshTransactions();
    }, 500);
    
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
    WebSocketManager.destroy();
  }
});

// Add a global $t function to help with i18n errors
window.app.config.globalProperties.$t = function(key) {
  return key;
};

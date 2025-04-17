// Helper function to map transaction objects (works for both invoices and payments)
const mapTransaction = function(transaction, type) {
  // Create a clean copy
  const mapped = {...transaction};
  
  // Set type and direction
  mapped.type = type || (transaction.payment_hash ? 'invoice' : 'payment');
  mapped.direction = mapped.type === 'invoice' ? 'incoming' : 'outgoing';
  
  // Format date consistently
  if (mapped.created_at) {
    try {
      mapped.date = Quasar.date.formatDate(new Date(mapped.created_at), 'YYYY-MM-DD HH:mm');
    } catch (e) {
      console.error('Error formatting date:', e, mapped.created_at);
      mapped.date = 'Invalid Date';
    }
  }
  
  // Ensure extra exists and contains asset info
  mapped.extra = mapped.extra || {};
  
  if (mapped.type === 'invoice') {
    // For invoices
    if (!mapped.extra.asset_amount && mapped.asset_amount) {
      mapped.extra.asset_amount = mapped.asset_amount;
    }
    
    if (!mapped.extra.asset_id && mapped.asset_id) {
      mapped.extra.asset_id = mapped.asset_id;
    }
  } else {
    // For payments
    mapped.extra = {
      asset_amount: mapped.asset_amount,
      asset_id: mapped.asset_id,
      fee_sats: mapped.fee_sats
    };
  }
  
  return mapped;
};

// Use the shared mapping function for both types
const mapInvoice = function(invoice) {
  return mapTransaction(invoice, 'invoice');
};

const mapPayment = function(payment) {
  return mapTransaction(payment, 'payment');
};

window.app = Vue.createApp({
  el: '#vue',
  mixins: [windowMixin],
  data() {
    return {
      settings: {
        tapd_host: '',
        tapd_network: 'signet',
        tapd_tls_cert_path: '',
        tapd_macaroon_path: '',
        tapd_macaroon_hex: '',
        lnd_macaroon_path: '',
        lnd_macaroon_hex: ''
      },
      showSettings: false,
      assets: [],
      invoices: [],
      payments: [],
      combinedTransactions: [],

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

      // Created invoice data
      createdInvoice: null,

      // For sending payments
      paymentDialog: {
        show: false,
        selectedAsset: null,
        form: {
          paymentRequest: '',
          feeLimit: 1000
        },
        inProgress: false
      },

      // Success dialog
      successDialog: {
        show: false
      },

      // Form submission tracking
      isSubmitting: false,

      // For transaction list display
      transactionsLoading: false,
      transitionEnabled: false,
      transactionsTable: {
        columns: [
          {name: 'created_at', align: 'left', label: 'Date', field: 'date', sortable: true},
          {name: 'direction', align: 'center', label: 'Type', field: 'direction'},
          {name: 'memo', align: 'left', label: 'Description', field: 'memo'},
          {name: 'amount', align: 'right', label: 'Amount', field: row => row.asset_amount || row.extra?.asset_amount},
          {name: 'status', align: 'center', label: 'Status', field: 'status'}
        ],
        pagination: {
          rowsPerPage: 10,
          page: 1
        }
      },

      // Refresh state tracking
      refreshInterval: null,
      refreshCount: 0
    }
  },
  computed: {
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
    }
  },
  methods: {
    // Helper method to find asset name by asset_id
    findAssetName(assetId) {
      if (!assetId || !this.assets || this.assets.length === 0) return null;
      const asset = this.assets.find(a => a.asset_id === assetId);
      return asset ? asset.name : null;
    },

    toggleSettings() {
      this.showSettings = !this.showSettings
    },
    
    getSettings() {
      if (!this.g.user.wallets.length) return;
      const wallet = this.g.user.wallets[0];

      LNbits.api
        .request('GET', '/taproot_assets/api/v1/taproot/settings', wallet.adminkey)
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

      LNbits.api
        .request('PUT', '/taproot_assets/api/v1/taproot/settings', wallet.adminkey, this.settings)
        .then(response => {
          this.settings = response.data;
          this.showSettings = false;
        })
        .catch(err => {
          console.error('Failed to save settings:', err);
        });
    },
    
    getAssets() {
      if (!this.g.user.wallets.length) return;
      const wallet = this.g.user.wallets[0];

      LNbits.api
        .request('GET', '/taproot_assets/api/v1/taproot/listassets', wallet.adminkey)
        .then(response => {
          this.assets = Array.isArray(response.data) ? response.data : [];
          if (this.assets.length > 0) {
            this.updateTransactionDescriptions();
          }
        })
        .catch(err => {
          console.error('Failed to fetch assets:', err);
          this.assets = [];
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

      LNbits.api
        .request('GET', `/taproot_assets/api/v1/taproot/invoices?_=${timestamp}`, wallet.adminkey)
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

      const timestamp = new Date().getTime();

      LNbits.api
        .request('GET', `/taproot_assets/api/v1/taproot/payments?_=${timestamp}`, wallet.adminkey)
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
    
    // Invoice dialog methods
    openInvoiceDialog(asset) {
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

      LNbits.api
        .request('POST', '/taproot_assets/api/v1/taproot/invoice', wallet.adminkey, payload)
        .then(response => {
          this.createdInvoice = response.data;

          // Add asset name for display
          if (this.invoiceDialog.selectedAsset?.name) {
            this.createdInvoice.asset_name = this.invoiceDialog.selectedAsset.name;
          }

          // Copy to clipboard
          this.copyInvoice(response.data.payment_request || response.data.id);

          // Refresh transactions list
          this.refreshTransactions();
        })
        .catch(err => {
          console.error('Failed to create invoice:', err);
        })
        .finally(() => {
          this.isSubmitting = false;
        });
    },
    
    // Payment dialog methods
    openPaymentDialog(asset) {
      this.resetPaymentForm();
      this.paymentDialog.selectedAsset = asset;
      this.paymentDialog.show = true;
    },
    
    resetPaymentForm() {
      this.paymentDialog.form = {
        paymentRequest: '',
        feeLimit: 1000
      };
      this.paymentDialog.inProgress = false;
    },
    
    closePaymentDialog() {
      this.paymentDialog.show = false;
      this.resetPaymentForm();
    },
    
    async submitPaymentForm() {
      if (this.paymentDialog.inProgress || !this.g.user.wallets.length) return;
      if (!this.paymentDialog.form.paymentRequest) {
        console.error('Please enter an invoice to pay');
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
        const response = await LNbits.api.request(
          'POST',
          '/taproot_assets/api/v1/taproot/pay',
          wallet.adminkey,
          payload
        );

        // Show success and refresh data
        this.paymentDialog.show = false;
        this.successDialog.show = true;
        await this.getAssets();
        await this.refreshTransactions();

      } catch (error) {
        console.error('Payment failed:', error);
      } finally {
        this.paymentDialog.inProgress = false;
      }
    },
    
    // Utility methods
    copyInvoice(invoice) {
      const textToCopy = typeof invoice === 'string'
        ? invoice
        : (invoice.payment_request || invoice.id || JSON.stringify(invoice) || 'No invoice data available');

      if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
        navigator.clipboard.writeText(textToCopy)
          .then(() => {
            console.log('Invoice copied to clipboard');
          })
          .catch(err => {
            console.error('Clipboard API failed:', err);
            this.fallbackCopy(textToCopy);
          });
      } else {
        this.fallbackCopy(textToCopy);
      }
    },
    
    fallbackCopy(text) {
      const tempInput = document.createElement('input');
      tempInput.value = text;
      document.body.appendChild(tempInput);
      tempInput.select();
      document.execCommand('copy');
      document.body.removeChild(tempInput);
    },
    
    getStatusColor(status) {
      switch (status) {
        case 'paid':
        case 'completed':
          return 'positive';
        case 'pending':
          return 'warning';
        case 'expired':
          return 'negative';
        case 'cancelled':
        default:
          return 'grey';
      }
    },
    
    refreshTransactions() {
      this.getInvoices(true);
      this.getPayments(true);
    },
    
    startAutoRefresh() {
      this.stopAutoRefresh();
      this.refreshInterval = setInterval(() => {
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
    if (this.g.user.wallets.length) {
      this.getSettings();
      this.getAssets();
      this.getInvoices(true);
      this.getPayments(true);
      this.startAutoRefresh();
    }
  },
  
  mounted() {
    setTimeout(() => {
      this.refreshTransactions();
    }, 500);
  },
  
  activated() {
    if (this.g.user.wallets.length) {
      this.resetInvoiceForm();
      this.resetPaymentForm();
      this.refreshTransactions();
      this.getAssets();
      this.startAutoRefresh();
    }
  },
  
  deactivated() {
    this.stopAutoRefresh();
  },
  
  beforeUnmount() {
    this.stopAutoRefresh();
  }
});

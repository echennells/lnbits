// /home/ubuntu/lnbits/lnbits/extensions/taproot_assets/static/js/index.js

// Helper function to map and format invoice objects
const mapInvoice = invoice => {
  // Create a clean copy of the object
  const mappedInvoice = {...invoice};

  // Handle date formatting consistently
  if (mappedInvoice.created_at) {
    try {
      mappedInvoice.date = Quasar.date.formatDate(new Date(mappedInvoice.created_at), 'YYYY-MM-DD HH:mm');
    } catch (e) {
      console.error('Error formatting date:', e, mappedInvoice.created_at);
      mappedInvoice.date = 'Invalid Date';
    }
  }

  // Store original data for reference
  mappedInvoice._data = {...invoice};

  // Make sure extra is an object, not a string
  if (mappedInvoice.extra && typeof mappedInvoice.extra === 'string') {
    try {
      mappedInvoice.extra = JSON.parse(mappedInvoice.extra);
    } catch (e) {
      mappedInvoice.extra = {};
    }
  }

  return mappedInvoice;
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

      // For invoice list display
      invoicesLoading: false,
      transitionEnabled: false, // Flag to control CSS transitions
      invoicesTable: {
        columns: [
          {name: 'created_at', align: 'left', label: 'Date', field: 'date', sortable: true},
          {name: 'memo', align: 'left', label: 'Description', field: 'memo'},
          {name: 'amount', align: 'right', label: 'Amount', field: row => row.extra?.asset_amount || row.asset_amount},
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
          // Ensure we have a proper array
          this.assets = Array.isArray(response.data) ? response.data : [];
        })
        .catch(err => {
          console.error('Failed to fetch assets:', err);
          this.assets = []; // Fallback to empty array on error
        });
    },
    getInvoices(isInitialLoad = false) {
      if (!this.g.user.wallets.length) return;
      const wallet = this.g.user.wallets[0];
      
      // Only show loading indicator on initial load
      if (isInitialLoad || this.invoices.length === 0) {
        this.invoicesLoading = true;
      }

      // Add a timestamp to prevent browser caching
      const timestamp = new Date().getTime();
      this.refreshCount++;

      LNbits.api
        .request('GET', `/taproot_assets/api/v1/taproot/invoices?_=${timestamp}`, wallet.adminkey)
        .then(response => {
          // Process each invoice and create a new array
          const processedInvoices = Array.isArray(response.data) 
            ? response.data.map(invoice => mapInvoice(invoice))
            : [];
            
          // If no existing invoices yet or initial load, just set them
          if (this.invoices.length === 0 || isInitialLoad) {
            this.invoices = processedInvoices;
            
            // Enable transitions after initial data load
            setTimeout(() => {
              this.transitionEnabled = true;
            }, 500);
            return;
          }
          
          // Compare new data with existing data to see if anything has changed
          const hasChanges = this.checkForInvoiceChanges(processedInvoices);
          
          if (hasChanges) {
            // Only update if there are actual changes
            this.invoices = processedInvoices;
          }
        })
        .catch(err => {
          console.error('Failed to fetch invoices:', err);
        })
        .finally(() => {
          this.invoicesLoading = false;
        });
    },
    
    // Helper method to check if invoices have changed and mark changed rows
    checkForInvoiceChanges(newInvoices) {
      // If the length is different, something has changed
      if (this.invoices.length !== newInvoices.length) {
        return true;
      }
      
      // Create a map of existing invoices by ID for quick lookup
      const existingMap = {};
      this.invoices.forEach(invoice => {
        existingMap[invoice.id] = invoice;
      });
      
      let hasChanges = false;
      
      // Check each new invoice against existing ones
      for (const newInvoice of newInvoices) {
        const existingInvoice = existingMap[newInvoice.id];
        
        // If this invoice doesn't exist yet, it's a change
        if (!existingInvoice) {
          hasChanges = true;
          // Mark as new invoice for animation
          newInvoice._isNew = true;
          continue;
        }
        
        // If status has changed, mark it and track the change
        if (existingInvoice.status !== newInvoice.status) {
          hasChanges = true;
          // Copy previous status for transition effect
          newInvoice._previousStatus = existingInvoice.status;
          newInvoice._statusChanged = true;
        }
      }
      
      return hasChanges;
    },
    openInvoiceDialog(asset) {
      // Reset the form first
      this.resetInvoiceForm();

      // Set the selected asset
      this.invoiceDialog.selectedAsset = asset;

      // Show the dialog
      this.invoiceDialog.show = true;
    },
    resetInvoiceForm() {
      // Reset form data to defaults
      this.invoiceDialog.form = {
        amount: 1,
        memo: '',
        expiry: 3600
      };

      // Reset form state
      this.isSubmitting = false;
      this.createdInvoice = null;
    },
    closeInvoiceDialog() {
      // Hide the dialog
      this.invoiceDialog.show = false;

      // Reset the form
      this.resetInvoiceForm();
    },
    submitInvoiceForm() {
      // Prevent multiple submissions
      if (this.isSubmitting) {
        return;
      }

      if (!this.g.user.wallets.length) return;
      const wallet = this.g.user.wallets[0];

      // Mark form as submitting
      this.isSubmitting = true;

      // Build the payload
      const payload = {
        asset_id: this.invoiceDialog.selectedAsset.asset_id || '',
        amount: parseFloat(this.invoiceDialog.form.amount),
        memo: this.invoiceDialog.form.memo,
        expiry: this.invoiceDialog.form.expiry
      };

      // Add peer_pubkey if the asset has channel_info
      if (this.invoiceDialog.selectedAsset.channel_info &&
          this.invoiceDialog.selectedAsset.channel_info.peer_pubkey) {
        payload.peer_pubkey = this.invoiceDialog.selectedAsset.channel_info.peer_pubkey;
      }

      LNbits.api
        .request('POST', '/taproot_assets/api/v1/taproot/invoice', wallet.adminkey, payload)
        .then(response => {
          // Store the created invoice data
          this.createdInvoice = response.data;

          // Copy to clipboard
          this.copyInvoice(response.data.payment_request || response.data.id);

          // Refresh invoices list to include the new invoice
          this.refreshInvoices();
        })
        .catch(err => {
          console.error('Failed to create invoice:', err);
        })
        .finally(() => {
          // Reset submitting state
          this.isSubmitting = false;
        });
    },
    openPaymentDialog(asset) {
      // Reset the form first
      this.resetPaymentForm();

      // Set the selected asset
      this.paymentDialog.selectedAsset = asset;

      // Show the dialog
      this.paymentDialog.show = true;
    },
    resetPaymentForm() {
      // Reset form data to defaults
      this.paymentDialog.form = {
        paymentRequest: '',
        feeLimit: 1000
      };

      this.paymentDialog.inProgress = false;
    },
    closePaymentDialog() {
      // Hide the dialog
      this.paymentDialog.show = false;

      // Reset the form
      this.resetPaymentForm();
    },
    async submitPaymentForm() {
      if (this.paymentDialog.inProgress) {
        return;
      }

      if (!this.g.user.wallets.length) return;
      const wallet = this.g.user.wallets[0];

      // Validate payment request
      if (!this.paymentDialog.form.paymentRequest) {
        console.error('Please enter an invoice to pay');
        return;
      }

      try {
        // Mark payment as in progress
        this.paymentDialog.inProgress = true;

        // Create payload
        const payload = {
          payment_request: this.paymentDialog.form.paymentRequest,
          fee_limit_sats: this.paymentDialog.form.feeLimit
        };

        // Add peer_pubkey if the asset has channel_info
        if (this.paymentDialog.selectedAsset?.channel_info?.peer_pubkey) {
          payload.peer_pubkey = this.paymentDialog.selectedAsset.channel_info.peer_pubkey;
        }

        // Make the API request
        const response = await LNbits.api.request(
          'POST',
          '/taproot_assets/api/v1/taproot/pay',
          wallet.adminkey,
          payload
        );

        // Hide payment dialog and show success
        this.paymentDialog.show = false;
        this.successDialog.show = true;

        // Refresh data
        await this.getAssets();
        await this.refreshInvoices();

        console.log('Payment successful:', response.data);
      } catch (error) {
        console.error('Payment failed:', error);
      } finally {
        // Reset payment in progress flag
        this.paymentDialog.inProgress = false;
      }
    },
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
          return 'positive';
        case 'pending':
          return 'warning';
        case 'expired':
          return 'negative';
        case 'cancelled':
          return 'grey';
        default:
          return 'grey';
      }
    },
    refreshInvoices() {
      // Call getInvoices with true to force refresh (show loading)
      this.getInvoices(true);
    },
    startAutoRefresh() {
      this.stopAutoRefresh();

      // Use a longer interval to reduce server load
      this.refreshInterval = setInterval(() => {
        this.getInvoices();
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
      this.getInvoices(true); // Pass true for initial load
      this.startAutoRefresh();
    }
  },
  mounted() {
    // Initial refresh after component is mounted
    setTimeout(() => {
      this.refreshInvoices();
    }, 500);
  },
  activated() {
    // When the component is re-activated
    if (this.g.user.wallets.length) {
      // Reset any form state
      this.resetInvoiceForm();
      this.resetPaymentForm();

      // Refresh data
      this.getInvoices(true);
      this.getAssets();

      // Restart auto-refresh
      this.startAutoRefresh();
    }
  },
  deactivated() {
    // When the component is deactivated
    this.stopAutoRefresh();
  },
  beforeUnmount() {
    // Clean up
    this.stopAutoRefresh();
  }
});

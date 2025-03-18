// Helper function to map objects if needed
const mapObject = obj => {
  return obj
}

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
      showInvoiceForm: false,  // Start with the form hidden
      showInvoiceModal: false,
      assets: [], // Initialize as empty array
      invoices: [], // Initialize as empty array
      selectedAsset: null, // Track the selected asset object
      invoiceForm: {
        amount: 1,
        memo: '',
        expiry: 3600
      },
      createdInvoice: null
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
          if (LNbits && LNbits.utils && LNbits.utils.notifyApiError) {
            LNbits.utils.notifyApiError(err);
          }
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
          if (LNbits && LNbits.utils && LNbits.utils.notifySuccess) {
            LNbits.utils.notifySuccess('Settings saved successfully');
          }
        })
        .catch(err => {
          console.error('Failed to save settings:', err);
          if (LNbits && LNbits.utils && LNbits.utils.notifyApiError) {
            LNbits.utils.notifyApiError(err);
          }
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
          console.log('Loaded assets:', this.assets);
        })
        .catch(err => {
          console.error('Failed to fetch assets:', err);
          if (LNbits && LNbits.utils && LNbits.utils.notifyApiError) {
            LNbits.utils.notifyApiError(err);
          }
          this.assets = []; // Fallback to empty array on error
        });
    },
    getInvoices() {
      if (!this.g.user.wallets.length) return;
      const wallet = this.g.user.wallets[0];
      
      LNbits.api
        .request('GET', '/taproot_assets/api/v1/taproot/invoices', wallet.adminkey)
        .then(response => {
          this.invoices = response.data || []; // Ensure it's an array
        })
        .catch(err => {
          console.error('Failed to fetch invoices:', err);
          if (LNbits && LNbits.utils && LNbits.utils.notifyApiError) {
            LNbits.utils.notifyApiError(err);
          }
          this.invoices = []; 
        });
    },
    createInvoice(asset) {
      // Store the entire asset object
      this.selectedAsset = asset;
      console.log('Selected asset:', asset);
      
      // Show the invoice form
      this.showInvoiceForm = true;
      
      // Reset form values
      this.invoiceForm.amount = 1;
      this.invoiceForm.memo = '';
      this.invoiceForm.expiry = 3600;
    },
    resetForm() {
      console.log('Form reset');
      this.selectedAsset = null;
      this.invoiceForm.amount = 1;
      this.invoiceForm.memo = '';
      this.invoiceForm.expiry = 3600;
      this.createdInvoice = null;
      
      // Hide the form
      this.showInvoiceForm = false;
    },
    submitInvoice() {
      if (!this.g.user.wallets.length) return;
      const wallet = this.g.user.wallets[0];
      
      // Check if we have a selected asset
      if (!this.selectedAsset) {
        if (LNbits && LNbits.utils && LNbits.utils.notifyError) {
          LNbits.utils.notifyError('Please select an asset first by clicking RECEIVE on one of your assets.');
        }
        return;
      }
      
      // Find the asset_id
      let assetId = this.selectedAsset.asset_id || '';
      
      // Create the payload with the found asset ID
      const payload = {
        asset_id: assetId,
        amount: this.invoiceForm.amount,
        memo: this.invoiceForm.memo,
        expiry: this.invoiceForm.expiry
      };
      
      console.log('Submitting invoice:', payload);
      
      LNbits.api
        .request('POST', '/taproot_assets/api/v1/taproot/invoice', wallet.adminkey, payload)
        .then(response => {
          this.createdInvoice = response.data;
          if (LNbits && LNbits.utils && LNbits.utils.notifySuccess) {
            LNbits.utils.notifySuccess('Invoice created successfully');
          }
        })
        .catch(err => {
          console.error('Failed to create invoice:', err);
          if (LNbits && LNbits.utils && LNbits.utils.notifyApiError) {
            LNbits.utils.notifyApiError(err);
          }
        });
    },
    copyInvoice(invoice) {
      const textToCopy = typeof invoice === 'string'
        ? invoice
        : (invoice.payment_request || invoice.id || JSON.stringify(invoice) || 'No invoice data available');

      if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
        navigator.clipboard.writeText(textToCopy)
          .then(() => {
            if (LNbits && LNbits.utils && LNbits.utils.notifySuccess) {
              LNbits.utils.notifySuccess('Invoice copied to clipboard');
            }
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

      if (LNbits && LNbits.utils && LNbits.utils.notifySuccess) {
        LNbits.utils.notifySuccess('Invoice copied to clipboard (fallback)');
      }
    },
    formatDate(timestamp) {
      if (!timestamp) return '';
      const date = new Date(timestamp * 1000);
      return date.toLocaleString();
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
    }
  },
  created() {
    if (this.g.user.wallets.length) {
      this.getSettings();
      this.getAssets();
      this.getInvoices();
    }
  }
})

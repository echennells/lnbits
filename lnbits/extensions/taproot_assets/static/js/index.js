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
      showInvoiceForm: false,
      showInvoiceModal: false,
      assets: [], // Initialize as empty array
      invoices: [], // Initialize as empty array
      invoiceForm: {
        asset_id: '',
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
      if (!this.g.user.wallets.length) {
        console.log('No wallets found, skipping getSettings');
        return;
      }
      const wallet = this.g.user.wallets[0];
      console.log('Fetching settings with wallet:', wallet);
      LNbits.api
        .request('GET', '/taproot_assets/api/v1/taproot/settings', wallet.adminkey)
        .then(response => {
          this.settings = response.data;
          console.log('Settings data:', this.settings);
        })
        .catch(err => {
          console.error('Failed to fetch settings:', err);
          if (LNbits && LNbits.utils && LNbits.utils.notifyApiError) {
            LNbits.utils.notifyApiError(err);
          }
        })
    },
    saveSettings() {
      if (!this.g.user.wallets.length) {
        console.log('No wallets found, skipping saveSettings');
        return;
      }
      const wallet = this.g.user.wallets[0];
      LNbits.api
        .request('PUT', '/taproot_assets/api/v1/taproot/settings', wallet.adminkey, this.settings)
        .then(response => {
          this.settings = response.data;
          this.showSettings = false;
          if (LNbits && LNbits.utils && LNbits.utils.notifySuccess) {
            LNbits.utils.notifySuccess('Settings saved successfully');
          } else {
            console.log('Settings saved successfully');
          }
        })
        .catch(err => {
          console.error('Failed to save settings:', err);
          if (LNbits && LNbits.utils && LNbits.utils.notifyApiError) {
            LNbits.utils.notifyApiError(err);
          }
        })
    },
    getAssets() {
      if (!this.g.user.wallets.length) {
        console.log('No wallets found, skipping getAssets');
        return;
      }
      const wallet = this.g.user.wallets[0];
      console.log('Fetching assets with wallet:', wallet);
      LNbits.api
        .request('GET', '/taproot_assets/api/v1/taproot/listassets', wallet.adminkey)
        .then(response => {
          this.assets = response.data || []; // Ensure it's an array
          console.log('Assets data:', this.assets); // Debug the asset structure
        })
        .catch(err => {
          console.error('Failed to fetch assets:', err);
          if (LNbits && LNbits.utils && LNbits.utils.notifyApiError) {
            LNbits.utils.notifyApiError(err);
          }
          this.assets = []; // Fallback to empty array on error
        })
    },
    getInvoices() {
      if (!this.g.user.wallets.length) {
        console.log('No wallets found, skipping getInvoices');
        return;
      }
      const wallet = this.g.user.wallets[0];
      console.log('Fetching invoices with wallet:', wallet);
      LNbits.api
        .request('GET', '/taproot_assets/api/v1/taproot/invoices', wallet.adminkey)
        .then(response => {
          this.invoices = response.data || []; // Ensure it's an array
          console.log('Invoices data:', this.invoices); // Debug the invoice structure
        })
        .catch(err => {
          console.error('Failed to fetch invoices:', err);
          if (LNbits && LNbits.utils && LNbits.utils.notifyApiError) {
            LNbits.utils.notifyApiError(err);
          }
          this.invoices = []; // Fallback to empty array on error
        })
    },
    createInvoice(assetId) {
      this.setAssetName(assetId);
      this.showInvoiceForm = true;
    },
    setAssetName(assetId) {
      const asset = this.assets.find(a => a.id === assetId);
      this.invoiceForm.asset_id = asset ? (asset.name || `Unknown (${asset.type})`) : '';
    },
    submitInvoice() {
      if (!this.g.user.wallets.length) return
      const wallet = this.g.user.wallets[0]
      // Map the name back to ID for the API if needed
      const asset = this.assets.find(a => (a.name || `Unknown (${a.type})`) === this.invoiceForm.asset_id);
      this.invoiceForm.asset_id = asset ? asset.id : this.invoiceForm.asset_id;
      LNbits.api
        .request('POST', '/taproot_assets/api/v1/taproot/invoice', wallet.adminkey, this.invoiceForm)
        .then(response => {
          this.createdInvoice = response.data
          console.log('createdInvoice:', this.createdInvoice); // Debug the invoice structure
          this.showInvoiceForm = false
          this.showInvoiceModal = false
          this.getInvoices()
          if (LNbits && LNbits.utils && LNbits.utils.notifySuccess) {
            LNbits.utils.notifySuccess('Invoice created successfully');
          } else {
            console.log('Invoice created successfully');
          }
        })
        .catch(err => {
          console.error('Failed to create invoice:', err);
          if (LNbits && LNbits.utils && LNbits.utils.notifyApiError) {
            LNbits.utils.notifyApiError(err);
          }
        })
    },
    copyInvoice(invoice) {
      console.log('LNbits.utils:', LNbits.utils);
      console.log('Received invoice:', invoice);

      const textToCopy = typeof invoice === 'string'
        ? invoice
        : (invoice.payment_request || invoice.id || JSON.stringify(invoice) || 'No invoice data available');
      console.log('Attempting to copy:', textToCopy);

      if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
        navigator.clipboard.writeText(textToCopy)
          .then(() => {
            if (LNbits && LNbits.utils && LNbits.utils.notifySuccess) {
              LNbits.utils.notifySuccess('Invoice copied to clipboard');
            } else {
              console.log('Invoice copied to clipboard');
            }
          })
          .catch(err => {
            console.error('Clipboard API failed:', err);
            this.fallbackCopy(textToCopy);
          });
      } else {
        console.warn('navigator.clipboard not available, using fallback');
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
      } else {
        console.log('Invoice copied to clipboard (fallback)');
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
    console.log('LNbits.utils on app created:', LNbits.utils);

    if (this.g.user.wallets.length) {
      this.getSettings();
      this.getAssets();
      this.getInvoices();
    } else {
      console.log('No wallets found, skipping API calls');
    }
  }
})

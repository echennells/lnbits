// /home/ubuntu/lnbits/lnbits/extensions/taproot_assets/static/js/index.js
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
      invoices: [], // Keep this to prevent undefined errors
      selectedAsset: null, // Track the selected asset object
      invoiceForm: {
        amount: 1,
        memo: '',
        expiry: 3600
      },
      createdInvoice: null,

      // For Send functionality
      showPayModal: false,
      paymentRequest: '',
      feeLimit: 1000,
      paymentInProgress: false,
      showPaymentSuccessModal: false
    }
  },
  computed: {
    // Add a computed property to determine max invoice amount (inbound liquidity)
    maxInvoiceAmount() {
      if (!this.selectedAsset) return 0;

      // For channel assets, calculate remote capacity (inbound liquidity)
      if (this.selectedAsset.channel_info) {
        const totalCapacity = parseFloat(this.selectedAsset.channel_info.capacity);
        const localBalance = parseFloat(this.selectedAsset.channel_info.local_balance);
        // Remote capacity = Total capacity - Local balance
        return totalCapacity - localBalance;
      }

      // For non-channel assets, use amount
      return parseFloat(this.selectedAsset.amount);
    },
    // Add validation status
    isInvoiceAmountValid() {
      if (!this.selectedAsset) return false;
      return parseFloat(this.invoiceForm.amount) <= this.maxInvoiceAmount;
    }
  },
  watch: {
    // Add a watcher to ensure amount stays within limits
    'invoiceForm.amount': function(newAmount) {
      const amount = parseFloat(newAmount);
      const max = this.maxInvoiceAmount;

      // If amount exceeds max, cap it at max
      if (amount > max) {
        this.invoiceForm.amount = max;
        if (LNbits && LNbits.utils && LNbits.utils.notifyWarning) {
          LNbits.utils.notifyWarning(`Amount capped at maximum receivable: ${max}`);
        }
      }
    },
    // Add a watcher for the payment success modal
    'showPaymentSuccessModal': function(newVal, oldVal) {
      // When the modal is closed (changes from true to false)
      if (oldVal === true && newVal === false) {
        // Refresh the assets to show updated balances
        this.getAssets();
      }
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
      // Keep this method but make it do nothing (just set empty array)
      this.invoices = [];
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
    showSendForm(asset) {
      // Store the entire asset object
      this.selectedAsset = asset;
      console.log('Selected asset for sending:', asset);

      // Reset payment form
      this.paymentRequest = '';
      this.feeLimit = 1000;

      // Show the payment modal
      this.showPayModal = true;
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

      // Validate amount against maximum inbound liquidity (double-check)
      const amount = parseFloat(this.invoiceForm.amount);
      const max = this.maxInvoiceAmount;

      if (amount > max) {
        if (LNbits && LNbits.utils && LNbits.utils.notifyError) {
          LNbits.utils.notifyError(`Amount exceeds maximum receivable. Maximum: ${max}`);
        }
        this.invoiceForm.amount = max; // Force cap the amount
        return;
      }

      // Find the asset_id
      let assetId = this.selectedAsset.asset_id || '';

      // Create the payload with the found asset ID and peer_pubkey if available
      const payload = {
        asset_id: assetId,
        amount: parseFloat(this.invoiceForm.amount), // Ensure it's a number
        memo: this.invoiceForm.memo,
        expiry: this.invoiceForm.expiry
      };
      
      // Add peer_pubkey if the asset has channel_info
      if (this.selectedAsset.channel_info && this.selectedAsset.channel_info.peer_pubkey) {
        payload.peer_pubkey = this.selectedAsset.channel_info.peer_pubkey;
        console.log('Using peer_pubkey:', payload.peer_pubkey);
      }

      console.log('Submitting invoice:', payload);

      LNbits.api
        .request('POST', '/taproot_assets/api/v1/taproot/invoice', wallet.adminkey, payload)
        .then(response => {
          this.createdInvoice = response.data;
          
          // Automatically copy the invoice to clipboard
          this.copyInvoice(response.data.payment_request || response.data.id);
          
          if (LNbits && LNbits.utils && LNbits.utils.notifySuccess) {
            LNbits.utils.notifySuccess('Invoice created and copied to clipboard');
          }
        })
        .catch(err => {
          console.error('Failed to create invoice:', err);
          if (LNbits && LNbits.utils && LNbits.utils.notifyApiError) {
            LNbits.utils.notifyApiError(err);
          }
        });
    },
    async payInvoice() {
      if (!this.g.user.wallets.length) return;
      const wallet = this.g.user.wallets[0];

      // Check if we have a payment request
      if (!this.paymentRequest) {
        LNbits.utils.notifyError('Please enter an invoice to pay');
        return;
      }

      try {
        this.paymentInProgress = true;

      // Create payload with payment request and fee limit
      const payload = {
        payment_request: this.paymentRequest,
        fee_limit_sats: this.feeLimit
      };
      
      // Add peer_pubkey if the asset has channel_info
      if (this.selectedAsset && this.selectedAsset.channel_info && this.selectedAsset.channel_info.peer_pubkey) {
        payload.peer_pubkey = this.selectedAsset.channel_info.peer_pubkey;
        console.log('Using peer_pubkey for payment:', payload.peer_pubkey);
      }

      const response = await LNbits.api.request(
        'POST',
        '/taproot_assets/api/v1/taproot/pay',
        wallet.adminkey,
        payload
      );

        this.paymentInProgress = false;
        this.showPayModal = false;
        this.showPaymentSuccessModal = true;

        // Reset form
        this.paymentRequest = '';

        // Refresh asset list to show updated balances
        await this.getAssets();

        console.log('Payment successful:', response);
      } catch (error) {
        this.paymentInProgress = false;
        LNbits.utils.notifyApiError(error);
      }
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
      this.getInvoices(); // Keep this call, but the method now just sets an empty array
    }
  }
})

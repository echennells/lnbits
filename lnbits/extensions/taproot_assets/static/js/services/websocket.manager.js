/**
 * WebSocket Manager for Taproot Assets extension
 * Fixed to properly handle asset name updates
 */

const WebSocketManager = {
  // WebSocket connection instances
  connections: {
    invoices: null,
    payments: null,
    balances: null
  },
  
  // Configuration
  config: {
    reconnectDelay: 5000,  // 5 seconds
    maxReconnectAttempts: 5
  },
  
  // Connection state
  state: {
    connected: false,
    reconnectAttempts: 0,
    reconnectTimeout: null,
    fallbackPolling: false,
    pollingInterval: null,
    userId: null
  },
  
  /**
   * Initialize the WebSocket manager
   * @param {string} userId - User ID for WebSocket connections
   */
  initialize(userId) {
    if (!userId) {
      console.error('User ID is required for WebSocket initialization');
      return;
    }
    
    // Set user ID
    this.state.userId = userId;
    
    // Connect to WebSockets
    this.connect();
  },
  
  /**
   * Connect to all WebSockets
   */
  connect() {
    // Close any existing connections
    this.closeAll();
    
    // Reset state
    this.state.reconnectAttempts = 0;
    
    // Start connections
    this._connectInvoices();
    this._connectPayments();
    this._connectBalances();
    
    // Set connected state
    this.state.connected = true;
    
    // Update store with connection status
    this._updateStoreConnectionStatus({
      connected: true,
      reconnecting: false,
      fallbackPolling: false
    });
    
    console.log('WebSocket connections established');
  },
  
  /**
   * Connect to invoices WebSocket
   * @private
   */
  _connectInvoices() {
    if (!this.state.userId) return;
    
    try {
      const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${wsProtocol}//${window.location.host}/api/v1/ws/taproot-assets-invoices-${this.state.userId}`;
      
      this.connections.invoices = new WebSocket(wsUrl);
      this.connections.invoices.onmessage = this._handleInvoiceMessage.bind(this);
      this.connections.invoices.onclose = () => this._handleConnectionClose('invoices');
      this.connections.invoices.onerror = (err) => this._handleConnectionError('invoices', err);
    } catch (error) {
      console.error('Error connecting to invoices WebSocket:', error);
      this._handleConnectionError('invoices', error);
    }
  },
  
  /**
   * Connect to payments WebSocket
   * @private
   */
  _connectPayments() {
    if (!this.state.userId) return;
    
    try {
      const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${wsProtocol}//${window.location.host}/api/v1/ws/taproot-assets-payments-${this.state.userId}`;
      
      this.connections.payments = new WebSocket(wsUrl);
      this.connections.payments.onmessage = this._handlePaymentMessage.bind(this);
      this.connections.payments.onclose = () => this._handleConnectionClose('payments');
      this.connections.payments.onerror = (err) => this._handleConnectionError('payments', err);
    } catch (error) {
      console.error('Error connecting to payments WebSocket:', error);
      this._handleConnectionError('payments', error);
    }
  },
  
  /**
   * Connect to balances WebSocket
   * @private
   */
  _connectBalances() {
    if (!this.state.userId) return;
    
    try {
      const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${wsProtocol}//${window.location.host}/api/v1/ws/taproot-assets-balances-${this.state.userId}`;
      
      this.connections.balances = new WebSocket(wsUrl);
      this.connections.balances.onmessage = this._handleBalanceMessage.bind(this);
      this.connections.balances.onclose = () => this._handleConnectionClose('balances');
      this.connections.balances.onerror = (err) => this._handleConnectionError('balances', err);
    } catch (error) {
      console.error('Error connecting to balances WebSocket:', error);
      this._handleConnectionError('balances', error);
    }
  },
  
  /**
   * Handle invoice WebSocket message
   * @param {MessageEvent} event - WebSocket message event
   * @private
   */
  _handleInvoiceMessage(event) {
    try {
      const data = JSON.parse(event.data);
      console.log('Invoice WebSocket message received:', data);
      
      // First, process balance data if available
      if (data?.data?.asset_id) {
        this._processAssetInfo(data.data);
      }
      
      // Process with InvoiceService to update store
      if (window.InvoiceService) {
        const processedInvoice = InvoiceService.processWebSocketUpdate(data);
        
        // Check if this is a paid invoice notification
        if (processedInvoice && processedInvoice.status === 'paid') {
          console.log('Paid invoice detected, triggering notification and UI update');
          
          // Set global update flag similar to core LNbits implementation
          if (window.g) {
            window.g.updatePayments = !window.g.updatePayments;
            window.g.updatePaymentsHash = processedInvoice.payment_hash;
          }
          
          // Trigger notification through NotificationService
          if (window.NotificationService) {
            NotificationService.notifyInvoicePaid(processedInvoice);
          }
          
          // Force refresh of assets to update balances
          this._refreshAssets();
        }
      }
    } catch (error) {
      console.error('Error handling invoice WebSocket message:', error);
    }
  },
  
  /**
   * Handle payment WebSocket message
   * @param {MessageEvent} event - WebSocket message event
   * @private
   */
  _handlePaymentMessage(event) {
    try {
      const data = JSON.parse(event.data);
      console.log('Payment WebSocket message received:', data);
      
      // First, process asset info if available
      if (data?.data?.asset_id) {
        this._processAssetInfo(data.data);
      }
      
      // Process with PaymentService
      if (window.PaymentService) {
        const processedPayment = PaymentService.processWebSocketUpdate(data);
        
        // Check if this is a completed payment notification
        if (processedPayment && processedPayment.status === 'completed') {
          console.log('Completed payment detected, triggering UI update');
          
          // Force refresh of assets and transactions
          this._refreshAssets();
          this._refreshTransactions();
        }
      }
    } catch (error) {
      console.error('Error handling payment WebSocket message:', error);
    }
  },
  
  /**
   * Handle balance WebSocket message
   * @param {MessageEvent} event - WebSocket message event
   * @private
   */
  _handleBalanceMessage(event) {
    try {
      const data = JSON.parse(event.data);
      console.log('Balance WebSocket message received:', data);
      
      // Process asset data with AssetService
      if (data?.type === 'assets_update' && Array.isArray(data.data)) {
        if (window.AssetService && typeof window.AssetService.processWebSocketUpdate === 'function') {
          // Let AssetService handle the update
          AssetService.processWebSocketUpdate(data);
        } else {
          // Process ourselves if AssetService doesn't have the method
          this._processAssetUpdate(data.data);
        }
        
        // Also refresh transactions to ensure asset names are up to date
        this._refreshTransactions();
      }
    } catch (error) {
      console.error('Error handling balance WebSocket message:', error);
    }
  },
  
  /**
   * Process asset info from message data
   * @param {Object} data - Message data with asset info
   * @private
   */
  _processAssetInfo(data) {
    if (!data?.asset_id) return;
    
    // Ensure the global asset map exists
    if (!window.assetMap) window.assetMap = {};
    
    // Update the asset map with the info
    if (!window.assetMap[data.asset_id]) {
      window.assetMap[data.asset_id] = {
        name: data.asset_name || data.name || `Asset ${data.asset_id.substring(0, 8)}...`,
        type: data.type || 'unknown'
      };
    }
  },
  
  /**
   * Process a batch asset update
   * @param {Array} assets - Array of asset data
   * @private
   */
  _processAssetUpdate(assets) {
    if (!Array.isArray(assets)) return;
    
    // Ensure the global asset map exists
    if (!window.assetMap) window.assetMap = {};
    
    // Update the asset map with all assets
    assets.forEach(asset => {
      if (asset.asset_id) {
        window.assetMap[asset.asset_id] = {
          name: asset.name || `Asset ${asset.asset_id.substring(0, 8)}...`,
          type: asset.type || 'unknown',
          channel_info: asset.channel_info
        };
      }
    });
    
    // Update the store
    if (window.taprootStore?.actions?.setAssets && window.taprootStore.state?.assets) {
      // Merge with existing assets
      const existingAssets = [...window.taprootStore.state.assets];
      const assetIds = new Set(existingAssets.map(a => a.asset_id));
      
      // Update existing and add new
      const updatedAssets = [...existingAssets];
      assets.forEach(asset => {
        if (asset.asset_id) {
          if (assetIds.has(asset.asset_id)) {
            // Update existing
            const index = updatedAssets.findIndex(a => a.asset_id === asset.asset_id);
            if (index !== -1) {
              updatedAssets[index] = {...updatedAssets[index], ...asset};
            }
          } else {
            // Add new
            updatedAssets.push(asset);
          }
        }
      });
      
      // Update the store
      window.taprootStore.actions.setAssets(updatedAssets);
    }
  },
  
  /**
   * Refresh assets using the store
   * @private
   */
  _refreshAssets() {
    const wallet = window.taprootStore?.getters?.getCurrentWallet();
    if (wallet && window.AssetService) {
      AssetService.getAssets(wallet);
    }
  },
  
  /**
   * Refresh transactions using services
   * @private
   */
  _refreshTransactions() {
    const wallet = window.taprootStore?.getters?.getCurrentWallet();
    if (wallet) {
      if (window.InvoiceService) {
        InvoiceService.getInvoices(wallet, true);
      }
      if (window.PaymentService) {
        PaymentService.getPayments(wallet, true);
      }
    }
  },
  
  /**
   * Update the store's WebSocket status
   * @param {Object} status - WebSocket status object
   * @private
   */
  _updateStoreConnectionStatus(status) {
    if (window.taprootStore?.actions?.setWebsocketStatus) {
      window.taprootStore.actions.setWebsocketStatus(status);
    }
  },
  
  /**
   * Handle WebSocket connection close
   * @param {string} type - Type of connection that was closed
   * @private
   */
  _handleConnectionClose(type) {
    console.log(`WebSocket ${type} connection closed`);
    this.connections[type] = null;
    
    // Check if all connections are closed
    if (Object.values(this.connections).every(conn => conn === null)) {
      this.state.connected = false;
      
      // Update store
      this._updateStoreConnectionStatus({
        connected: false,
        reconnecting: this.state.reconnectTimeout !== null
      });
      
      // Attempt reconnection
      this._scheduleReconnect();
      
      // Start fallback polling if needed
      this._startFallbackPolling();
    }
  },
  
  /**
   * Handle WebSocket connection error
   * @param {string} type - Type of connection with error
   * @param {Error} error - Error object
   * @private
   */
  _handleConnectionError(type, error) {
    console.error(`WebSocket ${type} connection error:`, error);
    
    // Close the connection if still open
    if (this.connections[type] && 
        this.connections[type].readyState !== WebSocket.CLOSED && 
        this.connections[type].readyState !== WebSocket.CLOSING) {
      this.connections[type].close();
    }
    this.connections[type] = null;
    
    // Check if all connections failed
    if (Object.values(this.connections).every(conn => conn === null)) {
      this.state.connected = false;
      
      // Update store
      this._updateStoreConnectionStatus({
        connected: false,
        reconnecting: true
      });
      
      // Attempt reconnection
      this._scheduleReconnect();
      
      // Start fallback polling immediately
      this._startFallbackPolling();
    }
  },
  
  /**
   * Schedule reconnection attempt
   * @private
   */
  _scheduleReconnect() {
    // Clear any existing reconnect timeout
    if (this.state.reconnectTimeout) {
      clearTimeout(this.state.reconnectTimeout);
      this.state.reconnectTimeout = null;
    }
    
    // Check if we've exceeded max attempts
    if (this.state.reconnectAttempts >= this.config.maxReconnectAttempts) {
      console.log('Maximum WebSocket reconnection attempts reached');
      
      // Update store
      this._updateStoreConnectionStatus({
        reconnecting: false,
        fallbackPolling: true
      });
      
      return;
    }
    
    // Increment attempts
    this.state.reconnectAttempts++;
    
    // Update store
    this._updateStoreConnectionStatus({
      reconnecting: true,
      reconnectAttempts: this.state.reconnectAttempts
    });
    
    // Schedule reconnect
    this.state.reconnectTimeout = setTimeout(() => {
      console.log(`Attempting WebSocket reconnection (${this.state.reconnectAttempts}/${this.config.maxReconnectAttempts})`);
      this.connect();
      this.state.reconnectTimeout = null;
    }, this.config.reconnectDelay);
  },
  
  /**
   * Start fallback polling for data
   * @private
   */
  _startFallbackPolling() {
    // Only start if not already polling
    if (this.state.fallbackPolling || this.state.pollingInterval) {
      return;
    }
    
    console.log('Starting fallback polling for data');
    this.state.fallbackPolling = true;
    
    // Update store
    this._updateStoreConnectionStatus({
      fallbackPolling: true
    });
    
    // Set up polling interval (every 10 seconds)
    this.state.pollingInterval = setInterval(() => {
      this._refreshAssets();
      this._refreshTransactions();
    }, 10000); // 10 seconds
  },
  
  /**
   * Stop fallback polling
   * @private
   */
  _stopFallbackPolling() {
    if (this.state.pollingInterval) {
      clearInterval(this.state.pollingInterval);
      this.state.pollingInterval = null;
    }
    this.state.fallbackPolling = false;
    
    // Update store
    this._updateStoreConnectionStatus({
      fallbackPolling: false
    });
  },
  
  /**
   * Check if a specific WebSocket is connected
   * @param {string} type - Type of connection to check
   * @returns {boolean} - Whether connection is established
   */
  isConnected(type) {
    if (!type || !this.connections[type]) {
      return false;
    }
    
    return this.connections[type].readyState === WebSocket.OPEN;
  },
  
  /**
   * Check if all WebSockets are connected
   * @returns {boolean} - Whether all connections are established
   */
  isFullyConnected() {
    return Object.keys(this.connections).every(type => this.isConnected(type));
  },
  
  /**
   * Close all WebSocket connections
   */
  closeAll() {
    // Close each connection
    Object.keys(this.connections).forEach(type => {
      if (this.connections[type]) {
        try {
          this.connections[type].close();
        } catch (e) {
          console.error(`Error closing ${type} WebSocket:`, e);
        }
        this.connections[type] = null;
      }
    });
    
    // Clear reconnect timeout if exists
    if (this.state.reconnectTimeout) {
      clearTimeout(this.state.reconnectTimeout);
      this.state.reconnectTimeout = null;
    }
    
    // Stop polling if active
    this._stopFallbackPolling();
    
    // Update state
    this.state.connected = false;
    
    // Update store
    this._updateStoreConnectionStatus({
      connected: false,
      reconnecting: false,
      fallbackPolling: false
    });
  },
  
  /**
   * Clean up when component is destroyed or unmounted
   */
  destroy() {
    this.closeAll();
    
    // Reset state
    this.state.userId = null;
    this.state.reconnectAttempts = 0;
  }
};

// Export the WebSocket manager
window.WebSocketManager = WebSocketManager;

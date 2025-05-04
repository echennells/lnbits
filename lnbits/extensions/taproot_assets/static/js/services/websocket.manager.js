/**
 * WebSocket Manager for Taproot Assets extension
 * Handles WebSocket connections, reconnection, and message processing
 * Updated to use the centralized store
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
  
  // Message handlers - can be overridden by the component
  handlers: {
    onPollingRequired: null
  },
  
  /**
   * Initialize the WebSocket manager
   * @param {string} userId - User ID for WebSocket connections
   * @param {Object} handlers - Event handlers for WebSocket messages
   */
  initialize(userId, handlers = {}) {
    if (!userId) {
      console.error('User ID is required for WebSocket initialization');
      return;
    }
    
    // Set user ID
    this.state.userId = userId;
    
    // Set custom polling handler if provided
    if (handlers.onPollingRequired) {
      this.handlers.onPollingRequired = handlers.onPollingRequired;
    }
    
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
    taprootStore.actions.setWebsocketStatus({
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
      
      // Process with InvoiceService to update store
      if (window.InvoiceService) {
        const processedInvoice = InvoiceService.processWebSocketUpdate(data);
        
        // Check if this is a paid invoice notification
        if (processedInvoice && processedInvoice.status === 'paid') {
          console.log('Paid invoice detected, triggering notification and UI update');
          
          // Call the Vue app's handlePaidInvoice method directly
          if (window.app && typeof window.app.handlePaidInvoice === 'function') {
            console.log('Calling app.handlePaidInvoice directly');
            window.app.handlePaidInvoice(processedInvoice);
          } 
          // Fallback to notification service if app method not available
          else if (window.NotificationService) {
            console.log('Fallback: using NotificationService.notifyInvoicePaid');
            NotificationService.notifyInvoicePaid(processedInvoice);
          }
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
      
      // Process with PaymentService and update store
      if (window.PaymentService) {
        const processedPayment = PaymentService.processWebSocketUpdate(data);
        
        // Check if this is a completed payment notification
        if (processedPayment && processedPayment.status === 'completed') {
          console.log('Completed payment detected, triggering UI update');
          
          // Call the Vue app's getAssets method directly to refresh assets
          if (window.app && typeof window.app.getAssets === 'function') {
            console.log('Calling app.getAssets directly to refresh balances');
            window.app.getAssets();
          }
          // Fallback to using the store
          else {
            console.log('Fallback: using store to refresh assets');
            const wallet = taprootStore.getters.getCurrentWallet();
            if (wallet && window.AssetService) {
              AssetService.getAssets(wallet);
            }
          }
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
      
      // Update the assets when we receive a balance update
      if (data.type === 'assets_update' && Array.isArray(data.data)) {
        // Call the Vue app's getAssets method directly
        if (window.app && typeof window.app.getAssets === 'function') {
          console.log('Calling app.getAssets directly to refresh balances from balance update');
          window.app.getAssets();
        }
        // Fallback to using the store
        else {
          console.log('Fallback: using store to refresh assets from balance update');
          const wallet = taprootStore.getters.getCurrentWallet();
          if (wallet) {
            AssetService.getAssets(wallet);
          }
        }
      }
    } catch (error) {
      console.error('Error handling balance WebSocket message:', error);
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
      taprootStore.actions.setWebsocketStatus({
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
      taprootStore.actions.setWebsocketStatus({
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
      taprootStore.actions.setWebsocketStatus({
        reconnecting: false,
        fallbackPolling: true
      });
      
      return;
    }
    
    // Increment attempts
    this.state.reconnectAttempts++;
    
    // Update store
    taprootStore.actions.setWebsocketStatus({
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
    taprootStore.actions.setWebsocketStatus({
      fallbackPolling: true
    });
    
    // Set up polling interval (every 10 seconds)
    this.state.pollingInterval = setInterval(() => {
      // Trigger polling callbacks
      if (this.handlers.onPollingRequired) {
        this.handlers.onPollingRequired();
      }
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
    taprootStore.actions.setWebsocketStatus({
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
    taprootStore.actions.setWebsocketStatus({
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
    
    // Clear all handlers
    this.handlers = {
      onPollingRequired: null
    };
    
    // Reset state
    this.state.userId = null;
    this.state.reconnectAttempts = 0;
  }
};

// Export the WebSocket manager
window.WebSocketManager = WebSocketManager;

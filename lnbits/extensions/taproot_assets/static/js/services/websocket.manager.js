/**
 * WebSocket Manager for Taproot Assets extension
 * Handles WebSocket connections, reconnection, and message processing
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
  
  // Message handlers
  handlers: {
    // To be set by the component
    onInvoiceMessage: null,
    onPaymentMessage: null,
    onBalanceMessage: null,
    onConnectionChange: null,
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
    
    // Set handlers if provided
    if (handlers.onInvoiceMessage) {
      this.handlers.onInvoiceMessage = handlers.onInvoiceMessage;
    }
    if (handlers.onPaymentMessage) {
      this.handlers.onPaymentMessage = handlers.onPaymentMessage;
    }
    if (handlers.onBalanceMessage) {
      this.handlers.onBalanceMessage = handlers.onBalanceMessage;
    }
    if (handlers.onConnectionChange) {
      this.handlers.onConnectionChange = handlers.onConnectionChange;
    }
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
    
    // Notify connection change
    this._notifyConnectionChange();
    
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
      
      // Call handler if set
      if (this.handlers.onInvoiceMessage) {
        this.handlers.onInvoiceMessage(data);
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
      
      // Call handler if set
      if (this.handlers.onPaymentMessage) {
        this.handlers.onPaymentMessage(data);
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
      
      // Call handler if set
      if (this.handlers.onBalanceMessage) {
        this.handlers.onBalanceMessage(data);
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
      this._notifyConnectionChange();
      
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
      this._notifyConnectionChange();
      
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
      return;
    }
    
    // Increment attempts
    this.state.reconnectAttempts++;
    
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
  },
  
  /**
   * Notify about connection state change
   * @private
   */
  _notifyConnectionChange() {
    if (this.handlers.onConnectionChange) {
      this.handlers.onConnectionChange({
        connected: this.state.connected,
        reconnecting: this.state.reconnectTimeout !== null,
        reconnectAttempts: this.state.reconnectAttempts,
        fallbackPolling: this.state.fallbackPolling
      });
    }
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
    this._notifyConnectionChange();
  },
  
  /**
   * Set event handlers for WebSocket messages
   * @param {Object} handlers - Event handlers object
   */
  setHandlers(handlers) {
    if (handlers.onInvoiceMessage) {
      this.handlers.onInvoiceMessage = handlers.onInvoiceMessage;
    }
    if (handlers.onPaymentMessage) {
      this.handlers.onPaymentMessage = handlers.onPaymentMessage;
    }
    if (handlers.onBalanceMessage) {
      this.handlers.onBalanceMessage = handlers.onBalanceMessage;
    }
    if (handlers.onConnectionChange) {
      this.handlers.onConnectionChange = handlers.onConnectionChange;
    }
    if (handlers.onPollingRequired) {
      this.handlers.onPollingRequired = handlers.onPollingRequired;
    }
  },
  
  /**
   * Clean up when component is destroyed or unmounted
   */
  destroy() {
    this.closeAll();
    
    // Clear all handlers
    this.handlers = {
      onInvoiceMessage: null,
      onPaymentMessage: null,
      onBalanceMessage: null,
      onConnectionChange: null,
      onPollingRequired: null
    };
    
    // Reset state
    this.state.userId = null;
    this.state.reconnectAttempts = 0;
  }
};

// Export the WebSocket manager
window.WebSocketManager = WebSocketManager;

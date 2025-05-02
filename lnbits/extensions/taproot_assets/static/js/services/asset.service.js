/**
 * Asset Service for Taproot Assets extension
 * Handles all asset-related functionality
 */

const AssetService = {
  // Local cache of assets
  _assetCache: [],
  
  /**
   * Get all assets with information about channels and balances
   * @param {Object} wallet - Wallet object with adminkey
   * @returns {Promise<Array>} - Promise that resolves with assets
   */
  async getAssets(wallet) {
    try {
      if (!wallet || !wallet.adminkey) {
        throw new Error('Valid wallet is required');
      }
      
      // Request assets from the API
      const response = await LNbits.api.request(
        'GET', 
        '/taproot_assets/api/v1/taproot/listassets', 
        wallet.adminkey
      );
      
      if (!response || !response.data) {
        return [];
      }
      
      // Process and cache the assets for later use
      const assets = Array.isArray(response.data) ? [...response.data] : [];
      this._assetCache = assets;
      
      // Get balances for assets
      if (assets.length > 0) {
        try {
          // Get all balances at once
          const balancesResponse = await LNbits.api.request(
            'GET', 
            '/taproot_assets/api/v1/taproot/asset-balances', 
            wallet.adminkey
          );
          
          if (balancesResponse && balancesResponse.data) {
            // Create a map of asset ID to balance
            const balanceMap = {};
            balancesResponse.data.forEach(balance => {
              if (balance.asset_id) {
                balanceMap[balance.asset_id] = balance.balance || 0;
              }
            });
            
            // Add balance information to assets
            assets.forEach(asset => {
              if (asset.asset_id && balanceMap[asset.asset_id] !== undefined) {
                asset.user_balance = balanceMap[asset.asset_id];
              } else {
                asset.user_balance = 0;
              }
            });
          }
        } catch (balanceError) {
          console.error('Error fetching asset balances:', balanceError);
          // Continue with assets even if balances fail
        }
      }
      
      return assets;
    } catch (error) {
      console.error('Failed to fetch assets:', error);
      throw error;
    }
  },
  
  /**
   * Get a specific asset by ID
   * @param {string} assetId - ID of the asset to get
   * @returns {Object|null} - Asset object or null if not found
   */
  getAssetById(assetId) {
    if (!assetId || this._assetCache.length === 0) {
      return null;
    }
    
    return this._assetCache.find(asset => asset.asset_id === assetId) || null;
  },
  
  /**
   * Get the name of an asset by ID
   * @param {string} assetId - ID of the asset to get name for
   * @returns {string} - Asset name or "Unknown" if not found
   */
  getAssetName(assetId) {
    const asset = this.getAssetById(assetId);
    return asset ? asset.name : 'Unknown';
  },

  /**
   * Check if a user can send this asset (has balance and active channel)
   * @param {Object} asset - Asset to check
   * @returns {boolean} - Whether user can send this asset
   */
  canSendAsset(asset) {
    if (!asset) return false;
    
    // First check if asset is active
    if (asset.channel_info && asset.channel_info.active === false) {
      return false;
    }
    
    // Then check if user has balance
    const userBalance = asset.user_balance || 0;
    return userBalance > 0;
  },
  
  /**
   * Get the maximum receivable amount for an asset
   * @param {Object} asset - Asset to get max receivable for
   * @returns {number} - Maximum receivable amount
   */
  getMaxReceivableAmount(asset) {
    if (!asset || !asset.channel_info) return 0;
    
    const channelInfo = asset.channel_info;
    if (channelInfo.capacity && channelInfo.local_balance) {
      const totalCapacity = parseFloat(channelInfo.capacity);
      const localBalance = parseFloat(channelInfo.local_balance);
      return totalCapacity - localBalance;
    }
    
    return 0;
  },
  
  /**
   * Get asset transactions
   * @param {Object} wallet - Wallet object with adminkey
   * @param {string|null} assetId - Asset ID (null for all assets)
   * @param {number} limit - Maximum transactions to return
   * @returns {Promise<Array>} - Promise that resolves with transactions
   */
  async getAssetTransactions(wallet, assetId = null, limit = 100) {
    try {
      if (!wallet || !wallet.adminkey) {
        throw new Error('Valid wallet is required');
      }
      
      // Build the URL with optional parameters
      let url = '/taproot_assets/api/v1/taproot/asset-transactions';
      const params = [];
      
      if (assetId) {
        params.push(`asset_id=${encodeURIComponent(assetId)}`);
      }
      
      if (limit) {
        params.push(`limit=${limit}`);
      }
      
      if (params.length > 0) {
        url += `?${params.join('&')}`;
      }
      
      // Make the API request
      const response = await LNbits.api.request('GET', url, wallet.adminkey);
      
      if (!response || !response.data) {
        return [];
      }
      
      return response.data;
    } catch (error) {
      console.error('Failed to fetch asset transactions:', error);
      throw error;
    }
  },
  
  /**
   * Get balance for a specific asset
   * @param {Object} wallet - Wallet object with adminkey
   * @param {string} assetId - Asset ID to get balance for
   * @returns {Promise<Object>} - Promise with asset balance
   */
  async getAssetBalance(wallet, assetId) {
    try {
      if (!wallet || !wallet.adminkey) {
        throw new Error('Valid wallet is required');
      }
      
      if (!assetId) {
        throw new Error('Asset ID is required');
      }
      
      const response = await LNbits.api.request(
        'GET', 
        `/taproot_assets/api/v1/taproot/asset-balance/${encodeURIComponent(assetId)}`, 
        wallet.adminkey
      );
      
      if (!response || !response.data) {
        throw new Error('Failed to get balance: No data returned');
      }
      
      return response.data;
    } catch (error) {
      console.error(`Failed to fetch balance for asset ${assetId}:`, error);
      throw error;
    }
  },
  
  /**
   * Clear the asset cache (useful when needing fresh data)
   */
  clearCache() {
    this._assetCache = [];
  }
};

// Export the service
window.AssetService = AssetService;

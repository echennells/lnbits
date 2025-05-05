/**
 * Simplified Asset Service for Taproot Assets extension
 * Further refactored to remove unnecessary conditionals
 */

const AssetService = {
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
      
      // Process the assets
      const assets = Array.isArray(response.data) ? [...response.data] : [];
      
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
      
      // Update the store - we know it's always available
      try {
        window.taprootStore.actions.setAssets(assets);
      } catch (e) {
        console.error('Error updating store with assets:', e);
      }
      
      return assets;
    } catch (error) {
      console.error('Failed to fetch assets:', error);
      return []; // Return empty array instead of throwing to maintain original behavior
    } finally {
      // Set loading state to false in store
      try {
        window.taprootStore.actions.setAssetsLoading(false);
      } catch (e) {
        // Ignore errors in finally block
      }
    }
  },
  
  /**
   * Get a specific asset by ID
   * @param {string} assetId - ID of the asset to get
   * @returns {Object|null} - Asset object or null if not found
   */
  getAssetById(assetId) {
    if (!assetId) return null;
    
    // Use the store directly - it's always available
    return window.taprootStore.state.assets.find(asset => asset.asset_id === assetId) || null;
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
  }
};

// Export the service
window.AssetService = AssetService;

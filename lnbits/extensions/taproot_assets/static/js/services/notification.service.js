/**
 * Notification Service for Taproot Assets extension
 * Uses native LNbits notification methods
 */

const NotificationService = {
  /**
   * Show a success notification
   * @param {string} message - Message to display
   */
  showSuccess(message) {
    if (window.LNbits && window.LNbits.utils && window.LNbits.utils.notifySuccess) {
      window.LNbits.utils.notifySuccess(message);
    } else {
      console.log('Success:', message);
    }
  },
  
  /**
   * Show an error notification
   * @param {string} message - Message to display
   */
  showError(message) {
    if (window.LNbits && window.LNbits.utils && window.LNbits.utils.notifyApiError) {
      // LNbits notifyApiError expects an error object with response.data.detail
      window.LNbits.utils.notifyApiError({
        response: {
          data: {
            detail: message
          }
        }
      });
    } else {
      console.error('Error:', message);
    }
  },
  
  /**
   * Show a warning notification
   * @param {string} message - Message to display
   */
  showWarning(message) {
    if (window.LNbits && window.LNbits.utils && window.LNbits.utils.notify) {
      window.LNbits.utils.notify({
        message: message,
        type: 'warning'
      });
    } else {
      console.warn('Warning:', message);
    }
  },
  
  /**
   * Show loading with message
   * @param {string} message - Message to display
   */
  showLoading(message = 'Loading...') {
    // In LNbits, there's no standard loading indicator
    // Log the loading message for now
    console.log('Loading started:', message);
  },
  
  /**
   * Hide loading indicator
   */
  hideLoading() {
    // In LNbits, there's no standard loading indicator
    // Log that loading has finished
    console.log('Loading finished');
  },
  
  /**
   * Notify user about an invoice being created
   * @param {Object} invoice - Created invoice data
   */
  notifyInvoiceCreated(invoice) {
    const assetName = invoice.asset_name || 'Asset';
    const amount = invoice.asset_amount || 0;
    
    this.showSuccess(`${assetName} invoice created successfully for ${amount} units`);
  },
  
  /**
   * Notify user about an invoice being paid
   * @param {Object} invoice - Paid invoice data
   */
  notifyInvoicePaid(invoice) {
    const assetName = invoice.asset_name || 'Unknown Asset';
    const amount = invoice.asset_amount || 0;
    
    this.showSuccess(`Invoice Paid: ${amount} ${assetName}`);
  },
  
  /**
   * Notify user about payment being sent
   * @param {Object} paymentResult - Payment result data
   */
  notifyPaymentSent(paymentResult) {
    let title, message;
    
    // Customize based on payment type
    if (paymentResult.internal_payment) {
      title = 'Internal Payment Processed';
      message = 'Payment to another user on this node has been processed successfully.';
    } else if (paymentResult.self_payment) {
      title = 'Self-Payment Processed';
      message = 'Self-payment has been processed successfully.';
    } else {
      title = 'Payment Successful!';
      message = 'Payment has been sent successfully.';
    }
    
    this.showSuccess(message);
    
    // Return formatted message for display in dialogs
    return { title, message };
  },
  
  /**
   * Show copy notification
   * @param {string} itemName - Name of the item that was copied
   */
  notifyCopied(itemName = 'Item') {
    this.showSuccess(`${itemName} copied to clipboard`);
  },
  
  /**
   * Process and display API error
   * @param {Object} error - Error object from API
   * @param {string} fallbackMessage - Fallback message if no error details
   * @returns {string} - Processed error message
   */
  processApiError(error, fallbackMessage = 'An error occurred') {
    let errorMessage = fallbackMessage;
    
    // Try to extract meaningful error message
    if (error) {
      if (error.isApiError && error.message) {
        errorMessage = error.message;
      } else if (error.response && error.response.data) {
        if (error.response.data.detail) {
          errorMessage = error.response.data.detail;
        } else if (error.response.data.message) {
          errorMessage = error.response.data.message;
        }
      } else if (error.message) {
        errorMessage = error.message;
      }
    }
    
    this.showError(errorMessage);
    return errorMessage;
  }
};

// Export the service
window.NotificationService = NotificationService;

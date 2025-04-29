/**
 * Utility functions for Taproot Assets extension
 */

// Helper function to map transaction objects (works for both invoices and payments)
function mapTransaction(transaction, type) {
  // Create a clean copy
  const mapped = {...transaction};
  
  // Set type and direction
  mapped.type = type || (transaction.payment_hash ? 'invoice' : 'payment');
  mapped.direction = mapped.type === 'invoice' ? 'incoming' : 'outgoing';
  
  // Format date consistently - exactly like LNbits
  if (mapped.created_at) {
    try {
      const date = new Date(mapped.created_at);
      // Format exactly like LNbits: YYYY-MM-DD HH:MM:SS
      mapped.date = Quasar.date.formatDate(date, 'YYYY-MM-DD HH:mm:ss');
      
      // Calculate "timeFrom" like LNbits
      const now = new Date();
      const diffMs = now - date;
      
      if (diffMs < 60000) { // less than a minute
        mapped.timeFrom = 'a minute ago';
      } else if (diffMs < 3600000) { // less than an hour
        const mins = Math.floor(diffMs / 60000);
        mapped.timeFrom = `${mins} minute${mins > 1 ? 's' : ''} ago`;
      } else if (diffMs < 86400000) { // less than a day
        const hours = Math.floor(diffMs / 3600000);
        mapped.timeFrom = `${hours} hour${hours > 1 ? 's' : ''} ago`;
      } else if (diffMs < 604800000) { // less than a week
        const days = Math.floor(diffMs / 86400000);
        mapped.timeFrom = `${days} day${days > 1 ? 's' : ''} ago`;
      } else {
        // Just use date for older items
        mapped.timeFrom = mapped.date;
      }
    } catch (e) {
      console.error('Error formatting date:', e, mapped.created_at);
      mapped.date = 'Unknown';
      mapped.timeFrom = 'Unknown';
    }
  }
  
  // Ensure extra exists and contains asset info
  mapped.extra = mapped.extra || {};
  
  if (mapped.type === 'invoice') {
    // For invoices
    if (!mapped.extra.asset_amount && mapped.asset_amount) {
      mapped.extra.asset_amount = mapped.asset_amount;
    }
    
    if (!mapped.extra.asset_id && mapped.asset_id) {
      mapped.extra.asset_id = mapped.asset_id;
    }
  } else {
    // For payments
    mapped.extra = {
      asset_amount: mapped.asset_amount,
      asset_id: mapped.asset_id,
      fee_sats: mapped.fee_sats
    };
  }
  
  return mapped;
}

// Use the shared mapping function for both types
function mapInvoice(invoice) {
  return mapTransaction(invoice, 'invoice');
}

function mapPayment(payment) {
  return mapTransaction(payment, 'payment');
}

// Format transaction date consistently
function formatTransactionDate(dateStr) {
  try {
    const date = new Date(dateStr);
    return Quasar.date.formatDate(date, 'YYYY-MM-DD HH:mm:ss');
  } catch (e) {
    return dateStr || 'Unknown date';
  }
}

// Shortify long text (like payment hash) - exactly like LNbits
function shortify(text, maxLength = 10) {
  if (!text) return '';
  if (text.length <= maxLength) return text;
  
  const half = Math.floor(maxLength / 2);
  return `${text.substring(0, half)}...${text.substring(text.length - half)}`;
}

// Copy text to clipboard - updated for better browser compatibility
function copyText(text, notifyCallback) {
  if (!text) {
    if (notifyCallback) {
      notifyCallback({
        message: 'Nothing to copy',
        color: 'warning',
        icon: 'warning',
        timeout: 1000
      });
    }
    return;
  }
  
  // Use the new clipboard API if available
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text)
      .then(() => {
        if (notifyCallback) {
          notifyCallback({
            message: 'Copied to clipboard',
            color: 'positive',
            icon: 'check',
            timeout: 1000
          });
        }
      })
      .catch(err => {
        console.error('Failed to copy text using Clipboard API:', err);
        fallbackCopy();
      });
  } else {
    fallbackCopy();
  }
  
  // Fallback method for older browsers
  function fallbackCopy() {
    try {
      // Create a temporary input element
      const tempInput = document.createElement('input');
      tempInput.style.position = 'fixed';
      tempInput.style.opacity = 0;
      tempInput.value = text;
      document.body.appendChild(tempInput);
      tempInput.select();
      tempInput.setSelectionRange(0, 99999); // For mobile devices
      
      // Execute copy command
      const successful = document.execCommand('copy');
      
      // Clean up
      document.body.removeChild(tempInput);
      
      // Execute notification callback if provided
      if (notifyCallback) {
        notifyCallback({
          message: successful ? 'Copied to clipboard' : 'Failed to copy',
          color: successful ? 'positive' : 'negative',
          icon: successful ? 'check' : 'error',
          timeout: 1000
        });
      }
    } catch (e) {
      console.error('Failed to copy text using fallback method:', e);
      if (notifyCallback) {
        notifyCallback({
          message: 'Failed to copy to clipboard',
          color: 'negative',
          icon: 'error',
          timeout: 1000
        });
      }
    }
  }
}

// Get status color for display
function getStatusColor(status) {
  switch (status) {
    case 'paid':
    case 'completed':
      return 'positive';
    case 'pending':
      return 'warning';
    case 'expired':
      return 'negative';
    case 'cancelled':
    default:
      return 'grey';
  }
}

// Format asset balance for display
function formatAssetBalance(balance, decimals = 0) {
  if (balance === undefined || balance === null) return '0';
  
  // Convert to number if it's a string
  const amount = typeof balance === 'string' ? parseFloat(balance) : balance;
  
  // Handle NaN or non-numeric values
  if (isNaN(amount)) return '0';
  
  // Format with the specified number of decimal places
  return amount.toFixed(decimals);
}

// Parse asset value from any format
function parseAssetValue(value) {
  if (!value) return 0;
  
  // Handle string values
  if (typeof value === 'string') {
    // Remove any non-numeric characters except decimal point
    const cleanValue = value.replace(/[^0-9.]/g, '');
    return parseFloat(cleanValue) || 0;
  }
  
  // Handle numeric values
  if (typeof value === 'number') {
    return isNaN(value) ? 0 : value;
  }
  
  return 0;
}

// Helper function to generate CSV content
function downloadCSV(rows, filename, notifyCallback) {
  if (!rows || rows.length === 0) {
    if (notifyCallback) {
      notifyCallback({
        message: 'No data to export',
        color: 'warning',
        timeout: 2000
      });
    }
    return;
  }
  
  // Get headers from first row
  const headers = Object.keys(rows[0]);
  
  // Create CSV content
  let csvContent = headers.join(',') + '\n';
  
  // Add rows
  rows.forEach(row => {
    const csvRow = headers.map(header => {
      // Handle values that might contain commas or quotes
      const value = row[header] !== undefined && row[header] !== null ? row[header].toString() : '';
      if (value.includes(',') || value.includes('"') || value.includes('\n')) {
        // Properly escape quotes by doubling them and wrap in quotes
        return '"' + value.replace(/"/g, '""') + '"';
      }
      return value;
    });
    csvContent += csvRow.join(',') + '\n';
  });
  
  // Create download link
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.setAttribute('href', url);
  link.setAttribute('download', filename);
  link.style.visibility = 'hidden';
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  
  if (notifyCallback) {
    notifyCallback({
      message: 'Transactions exported successfully',
      color: 'positive',
      icon: 'check_circle',
      timeout: 2000
    });
  }
}

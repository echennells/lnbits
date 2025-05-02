/**
 * Data Utilities for Taproot Assets extension
 * Shared functions for data transformation and formatting
 */

const DataUtils = {
  /**
   * Format a transaction date consistently
   * @param {string|Date} dateStr - Date string or object to format
   * @returns {string} - Formatted date string
   */
  formatDate(dateStr) {
    try {
      const date = dateStr instanceof Date ? dateStr : new Date(dateStr);
      if (window.Quasar && window.Quasar.date && window.Quasar.date.formatDate) {
        return window.Quasar.date.formatDate(date, 'YYYY-MM-DD HH:mm:ss');
      } else {
        // Fallback date formatter
        return date.toISOString().replace('T', ' ').substring(0, 19);
      }
    } catch (e) {
      console.error('Error formatting date:', e);
      return dateStr || 'Unknown date';
    }
  },
  
  /**
   * Calculate relative time from date (e.g. "2 hours ago")
   * @param {string|Date} dateStr - Date string or object 
   * @returns {string} - Relative time string
   */
  getRelativeTime(dateStr) {
    try {
      const date = dateStr instanceof Date ? dateStr : new Date(dateStr);
      const now = new Date();
      const diffMs = now - date;
      
      if (diffMs < 60000) { // less than a minute
        return 'a minute ago';
      } else if (diffMs < 3600000) { // less than an hour
        const mins = Math.floor(diffMs / 60000);
        return `${mins} minute${mins > 1 ? 's' : ''} ago`;
      } else if (diffMs < 86400000) { // less than a day
        const hours = Math.floor(diffMs / 3600000);
        return `${hours} hour${hours > 1 ? 's' : ''} ago`;
      } else if (diffMs < 604800000) { // less than a week
        const days = Math.floor(diffMs / 86400000);
        return `${days} day${days > 1 ? 's' : ''} ago`;
      } else {
        // Just use formatted date for older items
        return this.formatDate(date);
      }
    } catch (e) {
      console.error('Error calculating relative time:', e);
      return 'Unknown time';
    }
  },
  
  /**
   * Shortify a long string (e.g. payment hash)
   * @param {string} text - Text to shorten
   * @param {number} maxLength - Maximum length (default 10)
   * @returns {string} - Shortened text with ellipsis
   */
  shortify(text, maxLength = 10) {
    if (!text) return '';
    if (text.length <= maxLength) return text;
    
    const half = Math.floor(maxLength / 2);
    return `${text.substring(0, half)}...${text.substring(text.length - half)}`;
  },
  
  /**
   * Get CSS color class for a transaction status
   * @param {string} status - Transaction status
   * @returns {string} - CSS color class
   */
  getStatusColor(status) {
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
  },
  
  /**
   * Format asset balance for display
   * @param {number|string} balance - Balance to format
   * @param {number} decimals - Number of decimal places
   * @returns {string} - Formatted balance
   */
  formatAssetBalance(balance, decimals = 0) {
    if (balance === undefined || balance === null) return '0';
    
    // Convert to number if it's a string
    const amount = typeof balance === 'string' ? parseFloat(balance) : balance;
    
    // Handle NaN or non-numeric values
    if (isNaN(amount)) return '0';
    
    // Format with the specified number of decimal places
    return amount.toFixed(decimals);
  },
  
  /**
   * Parse asset value from any format to a number
   * @param {number|string} value - Value to parse
   * @returns {number} - Parsed numeric value
   */
  parseAssetValue(value) {
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
  },
  
  /**
   * Copy text to clipboard
   * @param {string} text - Text to copy
   * @param {Function} notifyCallback - Optional callback for notification
   * @returns {boolean} - Whether copy was successful
   */
  copyText(text, notifyCallback) {
    if (!text) {
      if (notifyCallback) {
        notifyCallback({
          message: 'Nothing to copy',
          color: 'warning',
          icon: 'warning',
          timeout: 1000
        });
      }
      return false;
    }
    
    try {
      // Use the built-in LNbits copy utility if available
      if (window.LNbits && window.LNbits.utils && window.LNbits.utils.copy) {
        window.LNbits.utils.copy(text);
        
        if (notifyCallback) {
          notifyCallback({
            message: 'Copied to clipboard',
            color: 'positive',
            icon: 'check',
            timeout: 1000
          });
        }
        
        return true;
      }
      
      // Fallback to document.execCommand
      const textArea = document.createElement('textarea');
      textArea.value = text;
      document.body.appendChild(textArea);
      textArea.select();
      const successful = document.execCommand('copy');
      document.body.removeChild(textArea);
      
      if (notifyCallback) {
        notifyCallback({
          message: successful ? 'Copied to clipboard' : 'Failed to copy',
          color: successful ? 'positive' : 'negative',
          icon: successful ? 'check' : 'error',
          timeout: 1000
        });
      }
      
      return successful;
    } catch (error) {
      console.error('Failed to copy text:', error);
      
      if (notifyCallback) {
        notifyCallback({
          message: 'Failed to copy to clipboard',
          color: 'negative',
          icon: 'error',
          timeout: 1000
        });
      }
      
      return false;
    }
  },
  
  /**
   * Combine and sort transactions (invoices and payments)
   * @param {Array} invoices - Array of invoices
   * @param {Array} payments - Array of payments
   * @returns {Array} - Combined and sorted transactions
   */
  combineTransactions(invoices, payments) {
    // Ensure we have arrays to work with
    const safeInvoices = Array.isArray(invoices) ? invoices : [];
    const safePayments = Array.isArray(payments) ? payments : [];
    
    // Combine and sort by date (most recent first)
    return [...safeInvoices, ...safePayments].sort((a, b) => {
      return new Date(b.created_at) - new Date(a.created_at);
    });
  },
  
  /**
   * Filter combined transactions based on criteria
   * @param {Array} transactions - Combined transactions to filter
   * @param {Object} filters - Filter criteria
   * @param {Object} searchData - Search criteria
   * @param {Object} dateRange - Date range for filtering
   * @returns {Array} - Filtered transactions
   */
  filterTransactions(transactions, filters, searchData, dateRange) {
    if (!transactions || !Array.isArray(transactions)) {
      return [];
    }
    
    let result = [...transactions];
    
    // Apply direction filter
    if (filters && filters.direction && filters.direction !== 'all') {
      result = result.filter(tx => tx.direction === filters.direction);
    }
    
    // Apply status filter
    if (filters && filters.status && filters.status !== 'all') {
      result = result.filter(tx => tx.status === filters.status);
    }
    
    // Apply memo search
    if (searchData && searchData.memo) {
      const searchLower = searchData.memo.toLowerCase();
      result = result.filter(tx => 
        tx.memo && tx.memo.toLowerCase().includes(searchLower)
      );
    }
    
    // Apply payment hash search
    if (searchData && searchData.payment_hash) {
      const searchLower = searchData.payment_hash.toLowerCase();
      result = result.filter(tx =>
        tx.payment_hash && tx.payment_hash.toLowerCase().includes(searchLower)
      );
    }
    
    // Apply date range filter
    if (dateRange && (dateRange.from || dateRange.to)) {
      result = result.filter(tx => {
        const txDate = new Date(tx.created_at);
        let matches = true;
        
        if (dateRange.from) {
          const fromDate = new Date(dateRange.from);
          fromDate.setHours(0, 0, 0, 0);
          if (txDate < fromDate) matches = false;
        }
        
        if (matches && dateRange.to) {
          const toDate = new Date(dateRange.to);
          toDate.setHours(23, 59, 59, 999);
          if (txDate > toDate) matches = false;
        }
        
        return matches;
      });
    }
    
    return result;
  },
  
  /**
   * Generate CSV content and trigger download
   * @param {Array} rows - Array of objects to convert to CSV
   * @param {string} filename - Filename for download
   * @param {Function} notifyCallback - Optional notification callback
   */
  downloadCSV(rows, filename, notifyCallback) {
    if (!rows || rows.length === 0) {
      if (notifyCallback) {
        notifyCallback({
          message: 'No data to export',
          color: 'warning',
          timeout: 2000
        });
      }
      return false;
    }
    
    try {
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
          message: 'Data exported successfully',
          color: 'positive',
          icon: 'check_circle',
          timeout: 2000
        });
      }
      
      return true;
    } catch (error) {
      console.error('Error generating CSV:', error);
      
      if (notifyCallback) {
        notifyCallback({
          message: 'Failed to export data',
          color: 'negative',
          icon: 'error',
          timeout: 2000
        });
      }
      
      return false;
    }
  }
};

// Export the utilities
window.DataUtils = DataUtils;

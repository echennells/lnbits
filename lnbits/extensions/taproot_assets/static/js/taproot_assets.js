// Taproot Assets Extension JavaScript

// Helper function to format asset amounts
function formatAssetAmount(amount, decimals = 0) {
  if (!amount) return '0';
  
  // Convert to number
  const num = parseFloat(amount);
  if (isNaN(num)) return amount;
  
  // Format with commas and decimals
  return num.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals
  });
}

// Helper function to truncate long strings (like asset IDs)
function truncateString(str, maxLength = 8) {
  if (!str) return '';
  if (str.length <= maxLength) return str;
  return str.substring(0, maxLength) + '...';
}

// Helper function to copy text to clipboard
function copyToClipboard(text) {
  navigator.clipboard.writeText(text).then(
    function() {
      // Success notification handled by Vue component
    },
    function(err) {
      console.error('Could not copy text: ', err);
    }
  );
}

// Helper function to open payment in wallet
function openInWallet(paymentRequest) {
  window.open('lightning:' + paymentRequest, '_blank');
}

// Helper function to format dates
function formatDate(dateStr) {
  if (!dateStr) return '';
  const date = new Date(dateStr);
  return date.toLocaleString();
}

// Export helpers for use in Vue components
window.TaprootAssetsHelpers = {
  formatAssetAmount,
  truncateString,
  copyToClipboard,
  openInWallet,
  formatDate
};

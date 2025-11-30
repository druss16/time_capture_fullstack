const express = require('express');
const path = require('path');

const app = express();

// Serve static files from dist folder
app.use(express.static(path.join(__dirname, 'dist'), {
  // Cache static assets for 1 year (they have hashed filenames)
  maxAge: '1y',
  // But don't cache index.html
  setHeaders: (res, filePath) => {
    if (filePath.endsWith('index.html')) {
      res.setHeader('Cache-Control', 'no-cache, no-store, must-revalidate');
    }
  }
}));

// SPA fallback - serve index.html for ALL routes that don't match a file
app.get('*', (req, res) => {
  res.sendFile(path.join(__dirname, 'dist', 'index.html'));
});

const PORT = process.env.PORT || 10000;

app.listen(PORT, '0.0.0.0', () => {
  console.log(`✅ Frontend server running on port ${PORT}`);
  console.log(`   Serving from: ${path.join(__dirname, 'dist')}`);
});
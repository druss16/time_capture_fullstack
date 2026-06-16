const express = require('express');
const path = require('path');
const app = express();

// Serve static files from dist folder
app.use(express.static(path.join(__dirname, 'dist'), {
  maxAge: '1y',
  setHeaders: (res, filePath) => {
    if (filePath.endsWith('index.html')) {
      res.setHeader('Cache-Control', 'no-cache, no-store, must-revalidate');
    }
  }
}));

// Microsoft publisher domain verification — must come BEFORE the SPA fallback
app.get('/.well-known/microsoft-identity-association.json', (req, res) => {
  res.json({
    associatedApplications: [
      { applicationId: '1178d566-16f1-4c70-b30a-a046c5879688' }
    ]
  });
});

// SPA fallback - new Express 5 syntax for catch-all
app.use((req, res) => {
  res.sendFile(path.join(__dirname, 'dist', 'index.html'));
});

const PORT = process.env.PORT || 10000;

app.listen(PORT, '0.0.0.0', () => {
  console.log(`✅ Frontend server running on port ${PORT}`);
});
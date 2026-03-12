self.addEventListener('install', (e) => {
  console.log('[Service Worker] Installiert');
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  console.log('[Service Worker] Aktiviert');
});

// Das hier ist der wichtigste Teil, damit Android die App akzeptiert!
self.addEventListener('fetch', (e) => {
  // Lässt die App normal mit dem Internet kommunizieren
});

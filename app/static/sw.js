const CACHE='rms-ledger-shell-v7';
const ASSETS=['/static/app.css?v=6','/static/app.js?v=7','/static/pwa.js?v=1','/static/icon.svg','/static/offline.html'];
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(ASSETS)).then(()=>self.skipWaiting())));
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k.startsWith('rms-ledger-shell-') && k!==CACHE).map(k=>caches.delete(k))))));
self.addEventListener('message',event=>{if(event.data==='ACTIVATE')self.skipWaiting()});
self.addEventListener('fetch',event=>{
 if(event.request.method!=='GET'||new URL(event.request.url).origin!==self.location.origin)return;
 const url=new URL(event.request.url);
 const path=url.pathname+url.search;
 if(ASSETS.includes(path))event.respondWith(caches.match(event.request).then(hit=>hit||fetch(event.request)));
 else if(event.request.mode==='navigate')event.respondWith(fetch(event.request).catch(()=>caches.match('/static/offline.html')));
 // Financial API responses, authentication pages and attachments are never cached.
});

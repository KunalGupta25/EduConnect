import { openDB, getAllAttendance, clearAttendance } from '/static/indexedDB.js';

const CACHE_NAME = 'attendance-app-cache-v1';
const urlsToCache = [
    '/',
    '/static/student.js',
    '/static/indexedDB.js',
    '/static/manifest.json',
    '/static/icons/icon-192x192.png',
    '/static/icons/icon-512x512.png',
    'https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/css/bootstrap.min.css',
    'https://code.jquery.com/jquery-3.5.1.slim.min.js',
    'https://cdn.jsdelivr.net/npm/popper.js@1.16.1/dist/umd/popper.min.js',
    'https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/js/bootstrap.min.js',
    '/static/app_privew/phone.png',
    '/static/app_privew/desktop.png'
];

self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => {
                console.log('Opened cache');
                return cache.addAll(urlsToCache);
            })
    );
});

self.addEventListener('fetch', event => {
    event.respondWith(
        caches.match(event.request)
            .then(response => {
                if (response) {
                    return response;
                }
                return fetch(event.request);
            })
    );
});

self.addEventListener('sync', event => {
    if (event.tag === 'sync-attendance') {
        event.waitUntil(syncOfflineAttendance());
    }
});

async function syncOfflineAttendance() {
    const db = await openDB();
    const records = await getAllAttendance(db);
    if (records.length > 0) {
        try {
            const response = await fetch('/api/sync-attendance', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(records)
            });
            const result = await response.json();
            if (result.success) {
                await clearAttendance(db);
                console.log('Offline attendance synced successfully!');
            } else {
                console.error('Error syncing offline attendance:', result.error);
            }
        } catch (error) {
            console.error('Error syncing offline attendance:', error);
        }
    }
}
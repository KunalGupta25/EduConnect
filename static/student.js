import { openDB, addAttendance, getAllAttendance, clearAttendance } from './indexedDB.js';

// Service Worker Registration
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/static/service-worker.js', { type: 'module' })
        .then(registration => {
            console.log('Service Worker registered with scope:', registration.scope);
            // Wait for the service worker to be active before registering sync
            navigator.serviceWorker.ready.then(function(reg) {
                if ('SyncManager' in window) {
                    reg.sync.register('sync-attendance');
                }
            });
        })
        .catch(error => {
            console.error('Service Worker registration failed:', error);
            displayNotification('Service Worker registration failed. Offline features may not work.', 'error');
        });
}

document.addEventListener('DOMContentLoaded', async () => {
    // Element References
    const markAttendanceBtn = document.getElementById('mark-attendance-btn');
    const networkStatus = document.getElementById('network-status');
    const webcamVideoMain = document.getElementById('webcam'); // Main webcam feed
    const webcamVideoModal = document.getElementById('webcam-modal'); // Modal webcam feed
    const notificationPanel = document.getElementById('notification-panel');
    const monthlyPercentage = document.getElementById('monthly-percentage');
    const daysPresent = document.getElementById('days-present');
    const daysAbsent = document.getElementById('days-absent');
    const requestManualAttendanceBtn = document.getElementById('request-manual-attendance-btn');
    const helpBtn = document.getElementById('help-btn');
    const markAttendanceLoading = document.getElementById('mark-attendance-loading');
    const faceCaptureModal = document.getElementById('faceCaptureModal');
    const captureBtn = document.getElementById('capture-btn');

    let db; // IndexedDB instance
    let currentStream; // To store the webcam stream for stopping

    // Initialize IndexedDB
    db = await openDB();

    // Loading state functions
    function showLoading() {
        markAttendanceBtn.disabled = true;
        markAttendanceLoading.classList.remove('hidden');
    }

    function hideLoading() {
        markAttendanceBtn.disabled = false;
        markAttendanceLoading.classList.add('hidden');
    }

    // Notification Display Function
    function displayNotification(message, type) {
        const notification = document.createElement('div');
        notification.className = `p-3 rounded-md text-sm font-medium flex items-center justify-between shadow-sm`;
        const isDark = document.documentElement.classList.contains('dark');

        let bgColorClass = '';
        let textColorClass = '';
        let icon = '';

        switch (type) {
            case 'success':
                bgColorClass = isDark ? 'bg-green-900/40' : 'bg-green-100';
                textColorClass = isDark ? 'text-green-200' : 'text-green-800';
                icon = '<i data-feather="check-circle" class="w-5 h-5 mr-2"></i>';
                break;
            case 'error':
                bgColorClass = isDark ? 'bg-red-900/40' : 'bg-red-100';
                textColorClass = isDark ? 'text-red-200' : 'text-red-800';
                icon = '<i data-feather="x-circle" class="w-5 h-5 mr-2"></i>';
                break;
            case 'info':
                bgColorClass = isDark ? 'bg-blue-900/40' : 'bg-blue-100';
                textColorClass = isDark ? 'text-blue-200' : 'text-blue-800';
                icon = '<i data-feather="info" class="w-5 h-5 mr-2"></i>';
                break;
            default:
                bgColorClass = isDark ? 'bg-gray-800' : 'bg-gray-100';
                textColorClass = isDark ? 'text-gray-200' : 'text-gray-800';
                icon = '';
        }

        const now = new Date();
        const timeString = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

        notification.innerHTML = `
            <div class="flex items-center">
                ${icon}
                <span>${message}</span>
            </div>
            <span class="text-xs text-gray-500">${timeString}</span>
        `;
        notification.classList.add(bgColorClass, textColorClass);

        notificationPanel.prepend(notification); // Add to top
        feather.replace(); // Re-render feather icons
    }

    // Function to clear notifications daily
    function clearNotificationsDaily() {
        const lastClearDate = localStorage.getItem('lastNotificationClearDate');
        const today = new Date().toDateString();

        if (lastClearDate !== today) {
            notificationPanel.innerHTML = ''; // Clear all notifications
            localStorage.setItem('lastNotificationClearDate', today);
        }
    }

    // Call on load and then periodically (e.g., every hour to catch day change)
    clearNotificationsDaily();
    setInterval(clearNotificationsDaily, 3600000); // Every hour

    // Network Status Update
    function updateNetworkStatus() {
        if (navigator.onLine) {
            networkStatus.textContent = 'Online';
            networkStatus.style.color = 'green';
            syncOfflineAttendance();
        } else {
            networkStatus.textContent = 'Offline';
            networkStatus.style.color = 'red';
            displayNotification('You are currently offline. Attendance will be synced when online.', 'info');
        }
    }

    window.addEventListener('online', updateNetworkStatus);
    window.addEventListener('offline', updateNetworkStatus);
    updateNetworkStatus();

    // Webcam Functions
    async function startWebcam(videoElement) {
        try {
            // Prefer the front-facing (selfie) camera
            currentStream = await navigator.mediaDevices.getUserMedia({
                video: {
                    facingMode: { ideal: 'user' },
                    width: { ideal: 1280 },
                    height: { ideal: 720 },
                    aspectRatio: 16 / 9
                }
            });
            videoElement.srcObject = currentStream;
        } catch (error) {
            // Fallback without facingMode in case the device doesn't support it
            try {
                currentStream = await navigator.mediaDevices.getUserMedia({ video: true });
                videoElement.srcObject = currentStream;
            } catch (fallbackError) {
                console.error('Error accessing webcam:', fallbackError);
                displayNotification('Could not access webcam. Please allow access and try again.', 'error');
            }
        }
    }

    function stopWebcam() {
        if (currentStream) {
            currentStream.getTracks().forEach(track => track.stop());
            currentStream = null;
        }
    }

    // Initial webcam start for main view
    startWebcam(webcamVideoMain);

    // Initial webcam start for main view
    startWebcam(webcamVideoMain);

    // Event Listeners
    markAttendanceBtn.addEventListener('click', () => {
        // Stop main webcam before opening modal
        stopWebcam();
        // Start modal webcam
        startWebcam(webcamVideoModal);
        // Show the modal directly
        faceCaptureModal.classList.add('show');
    });

    // Stop modal webcam when modal is closed
    faceCaptureModal.addEventListener('click', (event) => {
        if (event.target.classList.contains('modal') || event.target.closest('[data-dismiss="modal"]')) {
            stopWebcam();
            // Restart main webcam after modal closes
            startWebcam(webcamVideoMain);
            faceCaptureModal.classList.remove('show');
        }
    });

    captureBtn.addEventListener('click', async () => {
        showLoading(); // Show loading indicator
        const canvas = document.createElement('canvas');
        canvas.width = webcamVideoModal.videoWidth;
        canvas.height = webcamVideoModal.videoHeight;
        const context = canvas.getContext('2d');
        context.drawImage(webcamVideoModal, 0, 0, canvas.width, canvas.height);
        const imageDataURL = canvas.toDataURL('image/jpeg');

        const timestamp = new Date().toISOString();
        const studentId = await getStudentId();

        // --- NEW GEOLOCATION LOGIC START --- 
        if (navigator.geolocation) {
            navigator.geolocation.getCurrentPosition(async (position) => {
                const studentLatitude = position.coords.latitude;
                const studentLongitude = position.coords.longitude;

                const attendanceData = {
                    timestamp,
                    image: imageDataURL,
                    student_id: studentId,
                    latitude: studentLatitude,    // Add latitude
                    longitude: studentLongitude   // Add longitude
                };

                if (navigator.onLine) {
                    verifyFaceAndMarkAttendance({ ...attendanceData, is_offline: false });
                } else {
                    try {
                        // Store the image and metadata offline to verify later on server
                        await addAttendance(db, attendanceData);
                        displayNotification('Attendance marked offline. It will be synced when you are back online.', 'info');
                    } catch (error) {
                        console.error('Error saving attendance offline:', error);
                        displayNotification('Error marking attendance offline.', 'error');
                    } finally {
                        hideLoading(); // Hide loading indicator
                    }
                }
                // Hide the modal directly
                faceCaptureModal.classList.remove('show');
                stopWebcam();

            }, (error) => {
                console.error('Geolocation error:', error);
                displayNotification(`Unable to get your location: ${error.message}. Attendance not marked.`, 'error');
                hideLoading(); // Hide loading indicator
                faceCaptureModal.classList.remove('show');
                stopWebcam();
            });
        } else {
            displayNotification('Geolocation is not supported by your browser. Attendance not marked.', 'error');
            hideLoading(); // Hide loading indicator
            faceCaptureModal.classList.remove('show');
            stopWebcam();
        }
        // --- NEW GEOLOCATION LOGIC END --- 
    });

    requestManualAttendanceBtn.addEventListener('click', () => {
        displayNotification('Manual attendance request sent to teacher.', 'info');
        // In a real app, you'd send an API request here
    });

    helpBtn.addEventListener('click', () => {
        displayNotification('Please contact your administrator for assistance.', 'info');
        // In a real app, this might open a help page or chat
    });

    // API Calls
    function verifyFaceAndMarkAttendance(data) {
        fetch('/api/verify-face', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(data)
        })
        .then(response => response.json())
        .then(result => {
            if (result.success) {
                displayNotification('Attendance marked successfully!', 'success');
            } else {
                displayNotification('Error marking attendance: ' + result.error, 'error');
            }
        })
        .catch(error => {
            console.error('Error verifying face:', error);
            displayNotification('An error occurred during face verification. Please try again.', 'error');
        })
        .finally(() => {
            hideLoading(); // Hide loading indicator
        });
    }

    async function syncOfflineAttendance() {
        if (!db) {
            db = await openDB();
        }
        const records = await getAllAttendance(db);
        if (records.length > 0) {
            // No loading indicator here as this is background sync
            fetch('/api/sync-attendance', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(records)
            })
            .then(response => response.json())
            .then(async result => {
                if (result.success) {
                    await clearAttendance(db);
                    displayNotification('Offline attendance synced successfully!', 'success');
                } else {
                    displayNotification('Error syncing offline attendance: ' + result.error, 'error');
                }
            })
            .catch(error => {
                console.error('Error syncing offline attendance:', error);
                displayNotification('An error occurred while syncing offline attendance.', 'error');
            });
        }
    }

    async function getStudentId() {
        try {
            const response = await fetch('/api/get-student-id');
            const data = await response.json();
            return data.student_id;
        } catch (error) {
            console.error('Error fetching student ID:', error);
            displayNotification('Error fetching student ID. Please refresh the page.', 'error');
            return null; // Handle error appropriately
        }
    }

    async function loadMonthlyStats() {
        try {
            const response = await fetch('/api/student-monthly-stats'); // New endpoint needed
            const data = await response.json();

            if (data.success) {
                monthlyPercentage.textContent = `${data.percentage}%`;
                daysPresent.textContent = data.present_days;
                daysAbsent.textContent = data.absent_days;
            } else {
                displayNotification('Error loading monthly stats: ' + data.error, 'error');
            }
        } catch (error) {
            console.error('Error fetching monthly stats:', error);
            displayNotification('An error occurred while loading monthly stats.', 'error');
        }
    }

    // Initial load of monthly stats
    loadMonthlyStats();

    // Periodically update monthly stats (e.g., every 30 seconds)
    setInterval(loadMonthlyStats, 30000);
});
const API_BASE_URL = 'http://localhost:5005'; // URL вашего бэкенда

// --- Управление токенами ---
function storeTokens(accessToken, refreshToken) {
    localStorage.setItem('accessToken', accessToken);
    localStorage.setItem('refreshToken', refreshToken);
}

function getAccessToken() {
    return localStorage.getItem('accessToken');
}

function getRefreshToken() {
    return localStorage.getItem('refreshToken');
}

function clearTokens() {
    localStorage.removeItem('accessToken');
    localStorage.removeItem('refreshToken');
}

function isLoggedIn() {
    return !!getAccessToken();
}

// --- API Запросы ---
async function request(endpoint, method = 'GET', data = null, includeAuth = true) {
    const url = `${API_BASE_URL}${endpoint}`;
    const headers = {
        'Content-Type': 'application/json',
    };

    if (includeAuth && getAccessToken()) {
        headers['Authorization'] = `Bearer ${getAccessToken()}`;
    }

    const config = {
        method: method,
        headers: headers,
    };

    if (data) {
        if (data instanceof FormData) { // Для загрузки файлов
            delete headers['Content-Type']; // fetch сам установит правильный Content-Type для FormData
            config.body = data;
        } else {
            config.body = JSON.stringify(data);
        }
    }

    try {
        let response = await fetch(url, config);

        if (response.status === 401 && includeAuth && getRefreshToken()) {
            // Попытка обновить токен
            console.log('Access token expired or invalid. Attempting refresh...');
            const refreshSuccess = await refreshToken();
            if (refreshSuccess) {
                console.log('Token refreshed. Retrying original request...');
                headers['Authorization'] = `Bearer ${getAccessToken()}`; // Обновляем заголовок
                config.headers = headers; // Обновляем конфиг для повторного запроса
                response = await fetch(url, config); // Повторяем запрос
            } else {
                console.log('Token refresh failed. Logging out.');
                logoutUser(); // Если обновление не удалось, разлогиниваем
                window.location.href = 'login.html'; // Перенаправляем на логин
                return { // Возвращаем ошибку, чтобы вызывающая функция могла ее обработать
                    success: false,
                    status: response.status,
                    error: "Session expired. Please login again."
                };
            }
        }

        const responseData = await response.json().catch(() => ({})); // Если тело ответа пустое или не JSON

        if (!response.ok) {
            const errorMessage = responseData.msg || responseData.message || `Error: ${response.status} ${response.statusText}`;
            console.error('API Error:', errorMessage, 'Response Data:', responseData);
            return { success: false, status: response.status, error: errorMessage, data: responseData };
        }

        return { success: true, data: responseData, status: response.status };

    } catch (error) {
        console.error('Network or other error:', error);
        return { success: false, error: error.message || 'Network error' };
    }
}

async function refreshToken() {
    const currentRefreshToken = getRefreshToken();
    if (!currentRefreshToken) {
        return false;
    }

    try {
        const response = await fetch(`${API_BASE_URL}/auth/refresh`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh_token: currentRefreshToken }),
        });

        const data = await response.json();

        if (response.ok && data.access_token) {
            storeTokens(data.access_token, data.refresh_token || currentRefreshToken); // Если новый refresh не пришел, используем старый (зависит от бэка)
            console.log('Token refreshed successfully.');
            return true;
        } else {
            console.error('Failed to refresh token:', data.msg || response.statusText);
            clearTokens(); // Очищаем токены, так как refresh не удался
            return false;
        }
    } catch (error) {
        console.error('Error during token refresh:', error);
        clearTokens();
        return false;
    }
}

// --- Обновление UI в зависимости от статуса логина ---
function updateNavUI() {
    const navCreateListing = document.getElementById('nav-create-listing');
    const navProfile = document.getElementById('nav-profile');
    const navLogin = document.getElementById('nav-login');
    const navRegister = document.getElementById('nav-register');
    const navLogout = document.getElementById('nav-logout');
    const logoutButton = document.getElementById('logoutButton');

    if (isLoggedIn()) {
        if (navCreateListing) navCreateListing.style.display = 'block';
        if (navProfile) navProfile.style.display = 'block';
        if (navLogin) navLogin.style.display = 'none';
        if (navRegister) navRegister.style.display = 'none';
        if (navLogout) navLogout.style.display = 'block';
    } else {
        if (navCreateListing) navCreateListing.style.display = 'none';
        if (navProfile) navProfile.style.display = 'none';
        if (navLogin) navLogin.style.display = 'block';
        if (navRegister) navRegister.style.display = 'block';
        if (navLogout) navLogout.style.display = 'none';
    }

    if (logoutButton) {
        logoutButton.addEventListener('click', async () => {
            await logoutUser();
            window.location.href = 'index.html';
        });
    }
}

async function logoutUser() {
    const refreshTokenVal = getRefreshToken();
    if (refreshTokenVal) {
        await request('/auth/logout', 'POST', { refresh_token: refreshTokenVal });
    }
    clearTokens();
    updateNavUI();
    showAlert('Вы успешно вышли из системы.', 'success');
    // Перенаправление можно делать в вызывающей функции, если нужно
}


// --- Утилиты для UI ---
function showAlert(message, type = 'danger', duration = 5000) {
    const alertPlaceholder = document.getElementById('alert-placeholder');
    if (!alertPlaceholder) return;

    const wrapper = document.createElement('div');
    wrapper.innerHTML = [
        `<div class="alert alert-${type} alert-dismissible" role="alert">`,
        `   <div>${message}</div>`,
        '   <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>',
        '</div>'
    ].join('');

    alertPlaceholder.append(wrapper);

    setTimeout(() => {
        if (wrapper.firstChild) { // Проверяем, что алерт еще существует
             const bsAlert = new bootstrap.Alert(wrapper.firstChild);
             if (bsAlert) {
                 bsAlert.close();
             }
        }
    }, duration);
}

// Вызываем обновление UI при загрузке любой страницы, где подключен app.js
document.addEventListener('DOMContentLoaded', () => {
    updateNavUI();
});

// Функция для получения ID из query string (например, для listing-detail.html?id=X)
function getQueryParam(param) {
    const urlParams = new URLSearchParams(window.location.search);
    return urlParams.get(param);
}

// Функция для отображения лоадера (простая)
function showLoader(elementId = 'loader') {
    const loader = document.getElementById(elementId);
    if (loader) loader.style.display = 'block';
}

function hideLoader(elementId = 'loader') {
    const loader = document.getElementById(elementId);
    if (loader) loader.style.display = 'none';
}
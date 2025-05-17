document.addEventListener('DOMContentLoaded', () => {
const registerForm = document.getElementById('registerForm');
const loginForm = document.getElementById('loginForm');

if (registerForm) {
    registerForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const username = document.getElementById('username').value;
        const password = document.getElementById('password').value;
        const confirmPassword = document.getElementById('confirmPassword').value;

        if (password !== confirmPassword) {
            showAlert('Пароли не совпадают!', 'danger');
            return;
        }

        const response = await request('/auth/register', 'POST', {
            username: username,
            password: password,
            confirm_password: confirmPassword // Поле на бэкенде 'confirm_password'
        }, false); // Регистрация не требует токена

        if (response.success) {
            showAlert('Регистрация успешна! Теперь вы можете войти.', 'success');
            setTimeout(() => {
                window.location.href = 'login.html';
            }, 2000);
        } else {
            showAlert(response.error || 'Ошибка регистрации.', 'danger');
        }
    });
}

if (loginForm) {
    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
            const username = document.getElementById('username').value;
const password = document.getElementById('password').value;

        const response = await request('/auth/login', 'POST', {
            username: username,
            password: password
        }, false); // Логин не требует токена

        if (response.success && response.data.access_token && response.data.refresh_token) {
            storeTokens(response.data.access_token, response.data.refresh_token);
            updateNavUI(); // Обновить навигацию сразу
            showAlert('Вход успешен!', 'success');
            // Перенаправление на главную или профиль
            setTimeout(() => {
                window.location.href = 'index.html';
            }, 1000);
        } else {
            showAlert(response.error || 'Ошибка входа. Проверьте имя пользователя и пароль.', 'danger');
        }
    });
}
});